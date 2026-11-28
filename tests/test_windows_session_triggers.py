"""Tests for Windows lock/unlock and sleep/resume lighting triggers (PR 2B.2)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from tests.test_global_hotkeys import _FakeKernel32, _FakeUser32
from tests.test_thread_lifecycle import _wait_until
from wiz_console.adapters.storage.json_repositories import JsonSettingsRepository
from wiz_console.adapters.system.windows_session import (
    NOTIFY_FOR_THIS_SESSION,
    PBT_APMRESUMESUSPEND,
    PBT_APMSUSPEND,
    WM_POWERBROADCAST,
    WM_WTSSESSION_CHANGE,
    WTS_SESSION_LOCK,
    WTS_SESSION_UNLOCK,
    WindowsSessionMonitor,
    map_session_window_message,
)
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.domain.automation import SessionTriggersConfig


class _FakeWtsapi32:
    """Minimal injectable WTSAPI32 double recording WTS registrations."""

    def __init__(self) -> None:
        self.registered: list[tuple[int, int]] = []
        self.unregistered: list[int] = []

    def WTSRegisterSessionNotification(self, hwnd: int, flags: int) -> int:
        self.registered.append((hwnd, flags))
        return 1

    def WTSUnRegisterSessionNotification(self, hwnd: int) -> int:
        self.unregistered.append(hwnd)
        return 1


class _SessionFakeUser32(_FakeUser32):
    """Extends `_FakeUser32` with hidden window helpers for session monitor tests."""

    def __init__(self, kernel32: _FakeKernel32) -> None:
        super().__init__(kernel32)
        self.destroyed: list[int] = []

    def CreateWindowExW(self, *_args: object) -> int:
        return 9001

    def DestroyWindow(self, hwnd: int) -> int:
        self.destroyed.append(hwnd)
        return 1


def test_session_triggers_config_and_message_mapping() -> None:
    """Defaults stay disabled and Win32 WTS/power constants map to normalized names."""
    assert SessionTriggersConfig.from_dict(None) == SessionTriggersConfig(
        off_on_lock=False, restore_on_unlock=False, off_on_sleep=False
    )
    cfg = SessionTriggersConfig.from_dict({"off_on_lock": True, "restore_on_unlock": True})
    assert cfg.to_dict() == {
        "off_on_lock": True,
        "restore_on_unlock": True,
        "off_on_sleep": False,
    }
    assert map_session_window_message(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK) == "lock"
    assert map_session_window_message(WM_WTSSESSION_CHANGE, WTS_SESSION_UNLOCK) == "unlock"
    assert map_session_window_message(WM_POWERBROADCAST, PBT_APMSUSPEND) == "suspend"
    assert map_session_window_message(WM_POWERBROADCAST, PBT_APMRESUMESUSPEND) == "resume"
    assert map_session_window_message(WM_WTSSESSION_CHANGE, 99) is None


def test_windows_session_monitor_pumps_events_and_cleans_up() -> None:
    """Monitor registers WTS notifications, dispatches events, and unregisters cleanly."""
    kernel32 = _FakeKernel32()
    user32 = _SessionFakeUser32(kernel32)
    wtsapi32 = _FakeWtsapi32()
    events: list[str] = []

    monitor = WindowsSessionMonitor(
        user32=user32,
        kernel32=kernel32,
        wtsapi32=wtsapi32,
        platform="win32",
    )
    assert monitor.is_supported() is True
    monitor.start(events.append)
    try:
        thread_id = monitor._thread_id
        assert thread_id is not None
        assert wtsapi32.registered == [(9001, NOTIFY_FOR_THIS_SESSION)]
        user32.PostThreadMessageW(thread_id, WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, 0)
        user32.PostThreadMessageW(thread_id, WM_POWERBROADCAST, PBT_APMRESUMESUSPEND, 0)
        _wait_until(lambda: events == ["lock", "resume"], "session events never dispatched")
    finally:
        monitor.stop()

    assert wtsapi32.unregistered == [9001]
    assert user32.destroyed == [9001]


async def test_session_triggers_turn_off_on_lock_and_restore_previous_look(
    tmp_path: Path,
) -> None:
    """Lock powers off lit bulbs and unlock restores prior color/scene state when opted in."""
    async with FakeWizBulbServer(mac="a8bb50cc3344") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        settings_repo = JsonSettingsRepository(tmp_path / "settings.json")
        service = LightControlService(controller=controller, settings_repository=settings_repo)
        await service.discover_bulbs()
        await service.set_color(120, 200, 255, brightness=77)

        bridge = WebviewBridge(service=service)
        try:
            saved = await asyncio.to_thread(
                bridge.set_session_triggers,
                {"off_on_lock": True, "restore_on_unlock": True, "off_on_sleep": True},
            )
            assert saved["ok"] is True
            assert saved["session_triggers"]["off_on_lock"] is True

            lock_res = await asyncio.to_thread(bridge.trigger_session_event, "lock")
            assert lock_res["ok"] is True
            assert server.pilot_state["state"] is False

            unlock_res = await asyncio.to_thread(bridge.trigger_session_event, "unlock")
            assert unlock_res["ok"] is True
            assert server.pilot_state["state"] is True
            assert server.pilot_state["r"] == 120
            assert server.pilot_state["g"] == 200
            assert server.pilot_state["b"] == 255
            assert server.pilot_state["dimming"] == 77

            reloaded = settings_repo.load_settings()
            assert reloaded["session_triggers"]["off_on_sleep"] is True
        finally:
            bridge.shutdown()
