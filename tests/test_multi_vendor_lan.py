"""Tests for Multi-Vendor LAN controller foundation (WiZ + Govee) and v0.8.0 (PR 3.4)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.simulators.fake_govee_bulb import FakeGoveeBulbServer
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from wiz_console.adapters.govee.lan_controller import GoveeLanController
from wiz_console.adapters.registry import CompositeLightController
from wiz_console.adapters.storage.json_repositories import (
    JsonBulbRepository,
    JsonSettingsRepository,
)
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.domain.models import Bulb


def test_bulb_protocol_validation_and_backwards_compatibility() -> None:
    """Bulbs default to `wiz`, accept `govee`, serialize `protocol`, and reject unknowns."""
    default_bulb = Bulb.from_dict({"ip": "192.168.1.10"})
    assert default_bulb.protocol == "wiz"

    govee = Bulb(ip="192.168.1.25", protocol="Govee")
    assert govee.protocol == "govee"
    assert govee.name == "Govee Bulb (192.168.1.25)"
    assert govee.to_dict()["protocol"] == "govee"

    with pytest.raises(ValueError):
        Bulb(ip="192.168.1.25", protocol="unknown_vendor")


async def test_composite_controller_drives_mixed_wiz_and_govee_fixtures(tmp_path: Path) -> None:
    """Simultaneous WiZ + Govee bulbs register via IPC and obey unified service commands."""
    async with FakeWizBulbServer(mac="a8bb50ee0001") as wiz_srv, FakeGoveeBulbServer() as govee_srv:
        wiz_ctrl = WizUdpController(probe_candidates=[wiz_srv.endpoint])
        govee_ctrl = GoveeLanController(probe_candidates=[govee_srv.endpoint])
        composite = CompositeLightController({"wiz": wiz_ctrl, "govee": govee_ctrl})
        bulb_repo = JsonBulbRepository(data_dir=tmp_path)
        settings_repo = JsonSettingsRepository(tmp_path / "settings.json")
        service = LightControlService(
            controller=composite,
            bulb_repository=bulb_repo,
            settings_repository=settings_repo,
        )
        await service.discover_bulbs()

        bridge = WebviewBridge(service=service)
        try:
            added = await asyncio.to_thread(
                bridge.add_manual_bulb,
                govee_srv.endpoint,
                "Govee Desk Strip",
                "govee",
            )
            assert added["ok"] is True
            service.select_targets([wiz_srv.endpoint, govee_srv.endpoint])

            await service.set_color(45, 180, 255, brightness=82)
            assert (
                wiz_srv.pilot_state["r"],
                wiz_srv.pilot_state["g"],
                wiz_srv.pilot_state["b"],
            ) == (
                45,
                180,
                255,
            )
            assert govee_srv.state["color"] == {"r": 45, "g": 180, "b": 255}
            assert govee_srv.state["brightness"] == 82

            await service.set_temperature(4800, brightness=64)
            assert wiz_srv.pilot_state["temp"] == 4800
            assert govee_srv.state["colorTemInKelvin"] == 4800

            await service.set_power(False)
            assert wiz_srv.pilot_state["state"] is False
            assert govee_srv.state["onOff"] == 0

            # Persisted inventory retains Govee protocol routing on restart
            reloaded = bulb_repo.load_bulbs()
            assert next(b.protocol for b in reloaded if b.ip == govee_srv.endpoint) == "govee"
        finally:
            bridge.shutdown()
