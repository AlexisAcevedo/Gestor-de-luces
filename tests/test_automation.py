"""Unit and async integration tests for Circadian curve & Wake-Up sunrise ramp (PR 2B.1)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from tests.waits import wait_until_async
from wiz_console.adapters.storage.json_repositories import JsonSettingsRepository
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.domain.automation import (
    CircadianConfig,
    WakeupRampConfig,
    evaluate_circadian_target,
    evaluate_wakeup_progress,
)


def test_circadian_curve_and_wakeup_ramp_domain_math() -> None:
    """Circadian cosine curve peaks at solar noon and wakeup ramp eases monotonically."""
    cfg = CircadianConfig(
        enabled=True,
        sunrise_hour=6.0,
        sunset_hour=20.0,
        day_kelvin=6000,
        night_kelvin=2400,
        day_brightness=95,
        night_brightness=30,
    )
    assert evaluate_circadian_target(2.0, cfg) == (2400, 30)
    assert evaluate_circadian_target(6.0, cfg) == (2400, 30)
    assert evaluate_circadian_target(13.0, cfg) == (6000, 95)
    assert evaluate_circadian_target(20.0, cfg) == (2400, 30)
    assert evaluate_circadian_target(23.0, cfg) == (2400, 30)

    # Overnight wrap window check + validation + round-trip serialization
    overnight = CircadianConfig(
        enabled=True,
        sunrise_hour=20.0,
        sunset_hour=6.0,
        day_kelvin=5600,
        night_kelvin=2600,
        day_brightness=90,
        night_brightness=30,
    )
    assert evaluate_circadian_target(1.0, overnight) == (5600, 90)
    assert evaluate_circadian_target(22.0, overnight)[0] > 2600
    assert evaluate_circadian_target(12.0, overnight) == (2600, 30)
    assert CircadianConfig.from_dict(None) == CircadianConfig()
    assert CircadianConfig.from_dict(overnight.to_dict()) == overnight

    for invalid_kwargs in (
        {"sunrise_hour": True},
        {"sunrise_hour": "bad"},
        {"sunrise_hour": 24.5},
        {"sunrise_hour": 7.0, "sunset_hour": 7.0},
        {"interval_seconds": 5},
    ):
        with pytest.raises(ValueError):
            CircadianConfig(**invalid_kwargs)

    wake = WakeupRampConfig(
        enabled=True,
        target_hour=7,
        target_minute=15,
        duration_minutes=20,
        start_kelvin=2200,
        end_kelvin=5200,
        start_brightness=10,
        end_brightness=100,
        target_ips=["192.168.1.10", "192.168.1.10"],
    )
    assert wake.target_ips == ["192.168.1.10"]
    assert WakeupRampConfig.from_dict(None) == WakeupRampConfig()
    assert WakeupRampConfig.from_dict(wake.to_dict()) == wake
    for bad_wake in (
        {"target_hour": 24},
        {"target_minute": 60},
        {"duration_minutes": 0},
    ):
        with pytest.raises(ValueError):
            WakeupRampConfig(**bad_wake)

    k0, b0 = evaluate_wakeup_progress(0.0, wake)
    k_mid, b_mid = evaluate_wakeup_progress(0.5, wake)
    k1, b1 = evaluate_wakeup_progress(1.0, wake)
    assert (k0, b0) == (2200, 10)
    assert (k_mid, b_mid) == (3700, 55)
    assert (k1, b1) == (5200, 100)


async def test_automation_service_applies_circadian_and_wakeup_ramp_via_bridge(
    tmp_path: Path,
) -> None:
    """AutomationService persists settings, runs circadian & wakeup tasks, and cleans up."""
    async with FakeWizBulbServer(mac="a8bb50cc1122") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        settings_repo = JsonSettingsRepository(tmp_path / "settings.json")
        service = LightControlService(controller=controller, settings_repository=settings_repo)
        # Fast deterministic clock at solar noon (13:00) and fast wakeup step interval
        service._automation._now = lambda: datetime(2026, 11, 28, 13, 0, 0)
        service._automation._wakeup_step_interval = 0.005

        await service.discover_bulbs()
        bridge = WebviewBridge(service=service)
        try:
            res = await asyncio.to_thread(
                bridge.set_circadian_config,
                {
                    "enabled": True,
                    "sunrise_hour": 6.0,
                    "sunset_hour": 20.0,
                    "day_kelvin": 5800,
                    "night_kelvin": 2600,
                    "day_brightness": 90,
                    "night_brightness": 35,
                    "interval_seconds": 10,
                },
            )
            assert res["ok"] is True
            assert res["circadian"]["enabled"] is True

            await wait_until_async(
                lambda: server.pilot_state.get("temp") == 5800,
                "circadian tick never applied 5800K",
            )
            assert server.pilot_state["dimming"] == 90

            # Trigger sunrise wake-up ramp and wait for end brightness 100%
            wake_res = await asyncio.to_thread(
                bridge.set_wakeup_ramp_config,
                {
                    "enabled": True,
                    "target_hour": 7,
                    "target_minute": 30,
                    "duration_minutes": 15,
                    "start_kelvin": 2200,
                    "end_kelvin": 5000,
                    "start_brightness": 10,
                    "end_brightness": 100,
                },
            )
            assert wake_res["ok"] is True
            trig = await asyncio.to_thread(bridge.trigger_wakeup_ramp, None)
            assert trig["ok"] is True

            await wait_until_async(
                lambda: (
                    server.pilot_state.get("temp") == 5000
                    and server.pilot_state.get("dimming") == 100
                ),
                "wakeup ramp never reached 5000K / 100%",
            )

            # Verify persistence across reload
            reloaded = settings_repo.load_settings()
            assert reloaded["circadian"]["day_kelvin"] == 5800
            assert reloaded["wakeup_ramp"]["target_minute"] == 30
        finally:
            bridge.shutdown()
