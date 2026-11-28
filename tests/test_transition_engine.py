"""Tests for TransitionEngine crossfade smoothing, preemption, and persistence (PR 3.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from wiz_console.adapters.storage.json_repositories import JsonSettingsRepository
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.application.transition_engine import (
    TransitionEngine,
    interpolate_brightness,
    interpolate_kelvin,
    interpolate_rgb,
    normalize_transition_seconds,
)
from wiz_console.domain.value_objects import Color


def test_transition_math_and_validation() -> None:
    """Interpolation endpoints match inputs cleanly and duration validation enforces bounds."""
    assert normalize_transition_seconds(0) == 0.0
    assert normalize_transition_seconds(2.5) == 2.5
    for bad in (True, -0.1, 5.1, float("nan"), "fast"):
        with pytest.raises(ValueError):
            normalize_transition_seconds(bad)

    c0 = Color(0, 100, 200)
    c1 = Color(200, 200, 0)
    assert interpolate_rgb(c0, c1, 0.0) == c0
    assert interpolate_rgb(c0, c1, 0.5) == Color(100, 150, 100)
    assert interpolate_rgb(c0, c1, 1.0) == c1
    assert interpolate_kelvin(2700, 6500, 0.5) == 4600
    assert interpolate_brightness(20, 80, 0.5) == 50


async def test_transition_engine_preempts_and_reaches_final_state(tmp_path: Path) -> None:
    """Fades step smoothly against FakeWizBulbServer and newer commands preempt older fades."""
    async with FakeWizBulbServer(mac="a8bb50cc7788") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        settings_repo = JsonSettingsRepository(tmp_path / "settings.json")
        service = LightControlService(controller=controller, settings_repository=settings_repo)
        service._ctx.transition_engine = TransitionEngine(step_interval=0.002)
        await service.discover_bulbs()

        # Instant default 0.0s
        await service.set_color(10, 20, 30, brightness=40)
        assert (server.pilot_state["r"], server.pilot_state["g"], server.pilot_state["b"]) == (
            10,
            20,
            30,
        )

        # Configure smooth crossfade and run stepped color + temperature transitions
        bridge = WebviewBridge(service=service)
        try:
            saved = await asyncio.to_thread(bridge.set_transition_seconds, 0.5)
            assert saved["ok"] is True
            assert saved["transition_seconds"] == 0.5

            # Launch two sequential preemptable tasks
            t1 = asyncio.create_task(service.set_color(200, 100, 50, brightness=90))
            await asyncio.sleep(0.003)
            t2 = asyncio.create_task(service.set_color(50, 150, 250, brightness=80))
            await asyncio.gather(t1, t2)
            assert (server.pilot_state["r"], server.pilot_state["g"], server.pilot_state["b"]) == (
                50,
                150,
                250,
            )
            assert server.pilot_state["dimming"] == 80

            # Smooth Kelvin fade
            await service.set_temperature(3000, brightness=50)
            await service.set_temperature(5500, brightness=95)
            assert server.pilot_state["temp"] == 5500
            assert server.pilot_state["dimming"] == 95
            assert settings_repo.load_settings()["transition_seconds"] == 0.5
        finally:
            bridge.shutdown()
