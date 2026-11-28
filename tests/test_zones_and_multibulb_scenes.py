"""Tests for Zone entities, JsonZoneRepository, and heterogeneous multi-bulb scenes."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from wiz_console.adapters.storage.json_repositories import (
    JsonBulbRepository,
    JsonSceneRepository,
    JsonSettingsRepository,
    JsonZoneRepository,
)
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.domain.models import Bulb, Zone
from wiz_console.domain.scenes import BulbSceneState, CustomScene
from wiz_console.domain.value_objects import Color, LightMode


def test_zone_and_multibulb_scene_domain_serialization() -> None:
    """Validates Zone invariants and backward-compatible v1/v2 CustomScene serialization."""
    zone = Zone(
        id="living",
        name="Living Room",
        bulb_ips=["192.168.1.10", "192.168.1.10", "192.168.1.11"],
        icon="sofa",
    )
    assert zone.bulb_ips == ["192.168.1.10", "192.168.1.11"]
    restored = Zone.from_dict(zone.to_dict())
    assert restored == zone

    for bad_name in ("", "x" * 81):
        with pytest.raises(ValueError):
            Zone(id="z1", name=bad_name, bulb_ips=["192.168.1.10"])

    # v1 CustomScene omits bulb_states completely.
    v1_scene = CustomScene(id="s1", name="Warm", mode=LightMode.TEMPERATURE, temperature=3000)
    assert "bulb_states" not in v1_scene.to_dict()
    assert CustomScene.from_dict(v1_scene.to_dict()) == v1_scene

    # v2 CustomScene preserves heterogeneous per-bulb snapshots cleanly.
    v2_scene = CustomScene(
        id="s2",
        name="Studio Split",
        mode=LightMode.RGB,
        brightness=80,
        color=Color(255, 0, 128),
        bulb_states={
            "192.168.1.10": BulbSceneState(
                is_on=True,
                mode=LightMode.RGB,
                brightness=80,
                color=Color(255, 0, 128),
            ),
            "192.168.1.11": BulbSceneState(
                is_on=False,
                mode=LightMode.TEMPERATURE,
                brightness=50,
                temperature=2700,
            ),
        },
    )
    serialized = v2_scene.to_dict()
    assert "bulb_states" in serialized
    assert CustomScene.from_dict(serialized) == v2_scene


def test_json_zone_repository_persists_and_quarantines_corrupt_files(tmp_path: Path) -> None:
    """JsonZoneRepository writes atomically and quarantines invalid JSON roots."""
    repo = JsonZoneRepository(data_dir=tmp_path)
    assert repo.load_zones() == []

    zone = Zone(id="office", name="Office", bulb_ips=["192.168.1.20"])
    repo.save_zones([zone])
    assert repo.load_zones() == [zone]

    repo.file_path.write_text('{"corrupt": true}', encoding="utf-8")
    assert repo.load_zones() == []
    assert (tmp_path / "zones.json.corrupt").is_file()


async def test_zone_service_lifecycle_and_bulb_mac_and_delete_cascade(tmp_path: Path) -> None:
    """Zones persist, select targets, and cascade DHCP MAC moves and bulb removals."""
    async with (
        FakeWizBulbServer(mac="aa00bb00cc01") as bulb_a,
        FakeWizBulbServer(mac="aa00bb00cc02") as bulb_b,
        FakeWizBulbServer(mac="aa00bb00cc02") as bulb_b_moved,
    ):
        ep_a = bulb_a.endpoint
        ep_b = bulb_b.endpoint
        ep_b_new = bulb_b_moved.endpoint

        controller = WizUdpController(probe_candidates=[ep_a, ep_b])
        service = LightControlService(
            controller=controller,
            bulb_repository=JsonBulbRepository(data_dir=tmp_path),
            scene_repository=JsonSceneRepository(data_dir=tmp_path),
            settings_repository=JsonSettingsRepository(data_dir=tmp_path),
            zone_repository=JsonZoneRepository(data_dir=tmp_path),
        )
        await service.discover_bulbs(wait_time=0.2)

        zone = service.create_or_update_zone("Desk Pair", [ep_a, ep_b], icon="desk")
        assert [b.ip for b in service.list_bulbs()]
        assert service.select_zone(zone.id) == [ep_a, ep_b]

        # Capture distinct states for ep_a and ep_b into a multi-bulb CustomScene.
        await service.set_color(255, 80, 0, brightness=90, ips=[ep_a])
        await service.set_temperature(2700, brightness=40, ips=[ep_b])
        multi = service.save_custom_scene_from_current("Split Preset", capture_all_targets=True)
        assert multi.bulb_states is not None
        assert set(multi.bulb_states) == {ep_a, ep_b}

        # Apply heterogeneous scene over UDP and confirm each server gets its own parameters.
        await service.set_power(False, ips=[ep_a, ep_b])
        await service.apply_custom_scene(multi.id)
        assert bulb_a.pilot_state["state"] is True
        assert bulb_a.pilot_state["r"] == 255
        assert bulb_b.pilot_state["state"] is True
        assert bulb_b.pilot_state["temp"] == 2700
        assert bulb_b.pilot_state["dimming"] == 40

        # Simulate DHCP IP change on bulb_b: MAC reconciliation updates zone and scene keys.
        controller._probe_candidates = [ep_a, ep_b_new]  # type: ignore[attr-defined]
        await service.discover_bulbs(wait_time=0.2)

        updated_zone = service.get_zone(zone.id)
        assert updated_zone is not None
        assert updated_zone.bulb_ips == [ep_a, ep_b_new]
        updated_scene = service.get_custom_scene(multi.id)
        assert updated_scene is not None and updated_scene.bulb_states is not None
        assert set(updated_scene.bulb_states) == {ep_a, ep_b_new}

        # Removing bulb_a strips it from zones and custom scene bulb_states.
        service.remove_bulb(ep_a)
        reloaded = LightControlService(
            controller=WizUdpController(probe_candidates=[]),
            bulb_repository=JsonBulbRepository(data_dir=tmp_path),
            scene_repository=JsonSceneRepository(data_dir=tmp_path),
            settings_repository=JsonSettingsRepository(data_dir=tmp_path),
            zone_repository=JsonZoneRepository(data_dir=tmp_path),
        )
        zone_after = reloaded.get_zone(zone.id)
        assert zone_after is not None and zone_after.bulb_ips == [ep_b_new]
        scene_after = reloaded.get_custom_scene(multi.id)
        assert scene_after is not None and scene_after.bulb_states is not None
        assert set(scene_after.bulb_states) == {ep_b_new}

        reloaded.delete_zone(zone.id)
        assert reloaded.list_zones() == []


def test_zone_validation_errors_on_empty_ips() -> None:
    """Creating a zone without any bulb IP raises ValueError."""
    service = LightControlService(controller=WizUdpController(probe_candidates=[]))
    with pytest.raises(ValueError, match="at least one bulb"):
        service.create_or_update_zone("Empty", [])
    with pytest.raises(KeyError):
        service.select_zone("missing")
    with pytest.raises(KeyError):
        service.delete_zone("missing")
    assert Bulb(ip="192.168.1.2").ip == "192.168.1.2"
