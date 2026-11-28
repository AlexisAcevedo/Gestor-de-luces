"""Tests for opt-in foreground process profiles & local On-Air indicator (PR 2B.3)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from wiz_console.adapters.storage.json_repositories import JsonSettingsRepository
from wiz_console.adapters.system.windows_context import WindowsContextMonitor
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.domain.automation import (
    ContextAutomationConfig,
    ContextRule,
    OnAirConfig,
)
from wiz_console.ports.context_monitor import ContextSnapshot


class _FakeContextMonitor:
    """Deterministic in-memory `ContextMonitor` for unit/async tests."""

    def __init__(self, snapshot: ContextSnapshot | None = None) -> None:
        self.current = snapshot or ContextSnapshot()

    def is_supported(self) -> bool:
        return True

    def sample(self) -> ContextSnapshot:
        return self.current


class _FakeRegKey:
    def __init__(self, values: dict[str, int] | None = None, children: list[str] | None = None):
        self.values = values or {}
        self.children = children or []

    def __enter__(self) -> _FakeRegKey:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeWinReg:
    HKEY_CURRENT_USER = object()

    def __init__(self, tree: dict[str, _FakeRegKey]) -> None:
        self._tree = tree

    def OpenKey(self, _root: object, path: str) -> _FakeRegKey:
        if path in self._tree:
            return self._tree[path]
        raise FileNotFoundError(path)

    def EnumKey(self, key: _FakeRegKey, index: int) -> str:
        if 0 <= index < len(key.children):
            return key.children[index]
        raise OSError("No more keys")

    def QueryValueEx(self, key: _FakeRegKey, name: str) -> tuple[int, int]:
        if name in key.values:
            return key.values[name], 4
        raise FileNotFoundError(name)


def test_context_domain_validation_and_round_trip() -> None:
    """Context rules and On-Air config validate hex colors, ranges, and deduplicate rules."""
    cfg = ContextAutomationConfig.from_dict(
        {
            "enabled": True,
            "poll_seconds": 4,
            "on_air": {"enabled": True, "color_hex": "#FF00AA", "brightness": 80},
            "rules": [
                {"process_name": "Code.EXE", "action_type": "scene", "value": "12"},
                {"process_name": "code.exe", "action_type": "temp", "value": "4500"},
                {"process_name": "obs64.exe", "action_type": "color", "value": "#112233"},
            ],
        }
    )
    assert len(cfg.rules) == 2
    assert cfg.rules[0].process_name == "code.exe"
    assert cfg.rules[1].process_name == "obs64.exe"
    assert cfg.on_air.color_hex == "#ff00aa"
    assert ContextAutomationConfig.from_dict(None) == ContextAutomationConfig()

    for bad_rule in (
        {"process_name": "", "action_type": "scene", "value": "1"},
        {"process_name": "app.exe", "action_type": "invalid", "value": "1"},
        {"process_name": "app.exe", "action_type": "scene", "value": "99"},
        {"process_name": "app.exe", "action_type": "color", "value": "notahex"},
    ):
        with pytest.raises(ValueError):
            ContextRule.from_dict(bad_rule)

    with pytest.raises(ValueError):
        OnAirConfig(color_hex="bad")
    with pytest.raises(ValueError):
        ContextAutomationConfig(poll_seconds=1)


def test_windows_context_monitor_consentstore_and_foreground() -> None:
    """ConsentStore `LastUsedTimeStop == 0` marks mic active without recording anything."""
    mic_base = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    )
    winreg_fake = _FakeWinReg(
        {
            mic_base: _FakeRegKey(children=["NonPackaged", "Teams"]),
            f"{mic_base}\\NonPackaged": _FakeRegKey(children=[]),
            "Teams": _FakeRegKey(values={"LastUsedTimeStart": 100, "LastUsedTimeStop": 0}),
        }
    )

    class _NullUser32:
        def GetForegroundWindow(self) -> int:
            return 0

    class _NullKernel32:
        pass

    monitor = WindowsContextMonitor(
        user32=_NullUser32(),
        kernel32=_NullKernel32(),
        winreg_module=winreg_fake,
        platform="win32",
    )
    snap = monitor.sample()
    assert snap.mic_active is True
    assert snap.camera_active is False
    assert snap.foreground_process is None


async def test_on_air_overrides_process_rule_and_restores_previous_state(tmp_path: Path) -> None:
    """On-Air takes priority over app rules and restores previous look when context clears."""
    async with FakeWizBulbServer(mac="a8bb50cc5566") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        settings_repo = JsonSettingsRepository(tmp_path / "settings.json")
        monitor = _FakeContextMonitor()
        service = LightControlService(
            controller=controller,
            settings_repository=settings_repo,
            context_monitor=monitor,
        )
        await service.discover_bulbs()
        await service.set_temperature(4200, brightness=65)

        bridge = WebviewBridge(service=service)
        try:
            saved = await asyncio.to_thread(
                bridge.set_context_automation,
                {
                    "enabled": True,
                    "poll_seconds": 3,
                    "on_air": {
                        "enabled": True,
                        "watch_mic": True,
                        "watch_camera": True,
                        "color_hex": "#ff2244",
                        "brightness": 95,
                    },
                    "rules": [
                        {
                            "process_name": "code.exe",
                            "action_type": "temp",
                            "value": "5600",
                            "brightness": 85,
                        }
                    ],
                },
            )
            assert saved["ok"] is True

            # Active IDE rule triggers 5600K
            monitor.current = ContextSnapshot(foreground_process="code.exe", mic_active=False)
            status = await service.evaluate_context_once()
            assert status["active_reason"] == "rule:code.exe"
            assert server.pilot_state["temp"] == 5600

            # Active microphone overrides with On-Air RGB
            monitor.current = ContextSnapshot(foreground_process="code.exe", mic_active=True)
            status = await service.evaluate_context_once()
            assert status["on_air_active"] is True
            assert (server.pilot_state["r"], server.pilot_state["g"], server.pilot_state["b"]) == (
                255,
                34,
                68,
            )

            # Leaving call + tracked app restores original 4200K / 65%
            monitor.current = ContextSnapshot(foreground_process="explorer.exe", mic_active=False)
            status = await service.evaluate_context_once()
            assert status["active_reason"] is None
            assert server.pilot_state["temp"] == 4200
            assert server.pilot_state["dimming"] == 65
        finally:
            bridge.shutdown()
