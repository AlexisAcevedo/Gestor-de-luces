"""Tests for BulbCapabilities inference and RSSI/firmware diagnostics (PR 3.2)."""

from __future__ import annotations

from pathlib import Path

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.domain.models import Bulb, infer_bulb_capabilities


def test_infer_bulb_capabilities_matrix() -> None:
    """Module prefixes map accurately to RGB, Tunable White, Dimming, or fallback capabilities."""
    rgb_caps = infer_bulb_capabilities("ESP01_SHRGB1C_31")
    assert rgb_caps.supports_rgb is True
    assert rgb_caps.supports_tunable_white is True
    assert rgb_caps.min_kelvin == 2200

    tw_caps = infer_bulb_capabilities("ESP03_SHTW1_01")
    assert tw_caps.supports_rgb is False
    assert tw_caps.supports_tunable_white is True
    assert tw_caps.min_kelvin == 2700

    dim_caps = infer_bulb_capabilities("ESP06_SHDW_DIM_01")
    assert dim_caps.supports_rgb is False
    assert dim_caps.supports_tunable_white is True  # SHDW matches TW/SHDW before DIM

    fil_caps = infer_bulb_capabilities("ESP10_FIL_01")
    assert fil_caps.supports_rgb is False
    assert fil_caps.supports_tunable_white is False
    assert fil_caps.supports_dimming is True

    bulb = Bulb(
        ip="192.168.1.40",
        module_name="ESP03_SHTW1_01",
        rssi=-58,
        fw_version="1.32.2",
    )
    payload = bulb.to_dict()
    assert payload["rssi"] == -58
    assert payload["fw_version"] == "1.32.2"
    assert payload["capabilities"]["supports_rgb"] is False
    assert Bulb.from_dict(payload).fw_version == "1.32.2"
    assert Bulb.from_dict(payload).rssi == -58


async def test_udp_controller_and_service_record_rssi_and_fw_version(tmp_path: Path) -> None:
    """Discovery and refresh capture Wi-Fi RSSI and firmware version cleanly."""
    async with FakeWizBulbServer(
        mac="a8bb50cc9900",
        module_name="ESP03_SHTW1_01",
        rssi=-49,
        fw_version="1.33.0",
    ) as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(controller=controller)
        bulbs = await service.discover_bulbs()
        assert len(bulbs) == 1
        bulb = bulbs[0]
        assert bulb.rssi == -49
        assert bulb.fw_version == "1.33.0"
        assert bulb.capabilities.supports_rgb is False

        server.pilot_state["rssi"] = -63
        refreshed = await service.refresh_states([bulb.ip])
        assert refreshed[0].rssi == -63
