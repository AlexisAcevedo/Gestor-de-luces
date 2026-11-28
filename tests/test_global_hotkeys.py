"""Tests for domain hotkey normalization, Win32 RegisterHotKey adapter, and wiring."""

from __future__ import annotations

import asyncio
import queue
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from wiz_console.adapters.storage.json_repositories import JsonSettingsRepository
from wiz_console.adapters.system.windows_hotkeys import (
    ERROR_HOTKEY_ALREADY_REGISTERED,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    WM_HOTKEY,
    WM_QUIT,
    WindowsGlobalHotkeyManager,
    parse_win32_hotkey,
)
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.ui_webview.dispatch import JsApi
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.desktop import app as desktop_app
from wiz_console.desktop.app import DesktopApplication
from wiz_console.domain.value_objects import (
    DEFAULT_GLOBAL_HOTKEY_BINDINGS,
    HOTKEY_ACTIONS,
    default_global_hotkeys,
    normalize_global_hotkeys,
    normalize_hotkey_combo,
)


def test_normalize_hotkey_combo_and_global_hotkeys_validation() -> None:
    """Validates canonical modifier ordering, allowed keys, duplicate checks, and clearing."""
    assert normalize_hotkey_combo("alt + ctrl + shift + up") == "Ctrl+Alt+Shift+Up"
    assert normalize_hotkey_combo("windows+f12") == "Win+F12"
    assert normalize_hotkey_combo("  ") == ""

    for bad in ("P", "Ctrl+", "+P", "Ctrl+P+Q", "P+Ctrl", "Ctrl+UnknownKey", 123):
        with pytest.raises(ValueError):
            normalize_hotkey_combo(bad)

    defaults = default_global_hotkeys()
    assert defaults["enabled"] is False
    assert set(defaults["bindings"]) == set(HOTKEY_ACTIONS)

    custom = normalize_global_hotkeys(
        {
            "enabled": True,
            "bindings": {
                "toggle_power": "alt+ctrl+p",
                "toggle_window": "",
            },
        }
    )
    assert custom["enabled"] is True
    assert custom["bindings"]["toggle_power"] == "Ctrl+Alt+P"
    assert custom["bindings"]["toggle_window"] == ""

    with pytest.raises(ValueError, match="Duplicate hotkey binding"):
        normalize_global_hotkeys(
            {
                "enabled": True,
                "bindings": {
                    "toggle_power": "Ctrl+Alt+P",
                    "toggle_window": "alt+ctrl+p",
                },
            }
        )

    with pytest.raises(ValueError, match="Unknown hotkey action"):
        normalize_global_hotkeys({"enabled": False, "bindings": {"bogus_action": "Ctrl+Alt+X"}})


def test_parse_win32_hotkey_codes() -> None:
    """Maps normalized shortcuts to Win32 modifier bitmasks and virtual-key codes."""
    mods, vk = parse_win32_hotkey("Ctrl+Alt+Shift+Win+P")
    assert mods == (MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN | MOD_NOREPEAT)
    assert vk == ord("P")

    mods_up, vk_up = parse_win32_hotkey("Ctrl+Alt+Up")
    assert mods_up == (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT)
    assert vk_up == 0x26

    mods_fn, vk_fn = parse_win32_hotkey("Shift+F10")
    assert mods_fn == (MOD_SHIFT | MOD_NOREPEAT)
    assert vk_fn == 0x79

    with pytest.raises(ValueError):
        parse_win32_hotkey("")


class _FakeKernel32:
    """Controllable kernel32 double tracking thread identity and Win32 last error."""

    def __init__(self) -> None:
        self._tls = threading.local()

    def GetCurrentThreadId(self) -> int:
        return threading.get_ident()

    def SetLastError(self, code: int) -> None:
        self._tls.last_error = int(code)

    def GetLastError(self) -> int:
        return int(getattr(self._tls, "last_error", 0))


class _FakeUser32:
    """In-memory Win32 message queue and RegisterHotKey simulator."""

    def __init__(self, kernel32: _FakeKernel32, *, conflict_vk: int | None = None) -> None:
        self._kernel32 = kernel32
        self._conflict_vk = conflict_vk
        self._queue: queue.Queue[tuple[int, int, int]] = queue.Queue()
        self.registered: dict[int, tuple[int, int]] = {}
        self.unregister_calls: list[int] = []

    def PeekMessageW(self, _msg_ptr: Any, _hwnd: Any, _min: int, _max: int, _flags: int) -> int:
        return 0

    def GetMessageW(self, msg_ptr: Any, _hwnd: Any, _min: int, _max: int) -> int:
        message, wparam, lparam = self._queue.get()
        msg_obj = msg_ptr._obj
        msg_obj.message = message
        msg_obj.wParam = wparam
        msg_obj.lParam = lparam
        if message == WM_QUIT:
            return 0
        return 1

    def PostThreadMessageW(self, _thread_id: int, message: int, wparam: int, lparam: int) -> int:
        self._queue.put((int(message), int(wparam), int(lparam)))
        return 1

    def RegisterHotKey(self, _hwnd: Any, hotkey_id: int, modifiers: int, vk: int) -> int:
        if self._conflict_vk is not None and vk == self._conflict_vk:
            self._kernel32.SetLastError(ERROR_HOTKEY_ALREADY_REGISTERED)
            return 0
        self.registered[int(hotkey_id)] = (int(modifiers), int(vk))
        return 1

    def UnregisterHotKey(self, _hwnd: Any, hotkey_id: int) -> int:
        self.unregister_calls.append(int(hotkey_id))
        self.registered.pop(int(hotkey_id), None)
        return 1


def test_windows_global_hotkey_manager_registers_dispatches_and_stops() -> None:
    """Exercises start, config sync, conflict error codes, WM_HOTKEY dispatch, and cleanup."""
    kernel32 = _FakeKernel32()
    user32 = _FakeUser32(kernel32, conflict_vk=ord("M"))
    manager = WindowsGlobalHotkeyManager(user32=user32, kernel32=kernel32, platform="win32")
    assert manager.is_supported() is True

    triggered: list[str] = []
    done = threading.Event()

    def _on_hotkey(action_id: str) -> None:
        triggered.append(action_id)
        done.set()

    manager.start(_on_hotkey)
    try:
        errors = manager.apply_config(
            enabled=True,
            bindings=dict(DEFAULT_GLOBAL_HOTKEY_BINDINGS),
        )
        assert errors == {"toggle_music_sync": "in_use"}
        # 5 non-conflicting hotkeys registered
        assert len(user32.registered) == 5

        power_id = next(iter(user32.registered))
        user32.PostThreadMessageW(0, WM_HOTKEY, power_id, 0)
        assert done.wait(timeout=2.0) is True
        assert triggered == ["toggle_power"]

        disabled_errors = manager.apply_config(
            enabled=False,
            bindings=dict(DEFAULT_GLOBAL_HOTKEY_BINDINGS),
        )
        assert disabled_errors == {}
        assert user32.registered == {}
    finally:
        manager.stop()


def test_windows_global_hotkey_manager_non_windows_is_safe_noop() -> None:
    """Non-Windows hosts report unsupported without starting any background thread."""
    manager = WindowsGlobalHotkeyManager(platform="linux")
    assert manager.is_supported() is False
    manager.start(lambda _action: None)
    assert manager.apply_config(enabled=True, bindings=dict(DEFAULT_GLOBAL_HOTKEY_BINDINGS)) == {}
    manager.stop()


async def test_bridge_and_desktop_hotkeys_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persists global hotkeys, syncs Win32 errors on UI save, and triggers light actions."""
    async with FakeWizBulbServer(mac="a8bb50776655") as server:
        settings_repo = JsonSettingsRepository(data_dir=tmp_path)
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(controller=controller, settings_repository=settings_repo)
        bridge = WebviewBridge(service=service)
        kernel32 = _FakeKernel32()
        user32 = _FakeUser32(kernel32, conflict_vk=ord("A"))
        hotkey_mgr = WindowsGlobalHotkeyManager(user32=user32, kernel32=kernel32, platform="win32")

        monkeypatch.setattr(desktop_app, "resolve_default_data_dir", lambda: tmp_path)
        app = DesktopApplication(
            service=service,
            bridge=bridge,
            index_path=tmp_path / "index.html",
            icon_path=tmp_path / "app.ico",
            ui_dir=tmp_path,
            hotkeys=hotkey_mgr,
        )
        bridge.set_state_change_listener(app.on_state_changed)
        hotkey_mgr.start(app.on_global_hotkey)
        try:
            discovered = await asyncio.to_thread(bridge.discover_bulbs)
            assert discovered["ok"] is True
            assert len(discovered["bulbs"]) == 1

            saved = await asyncio.to_thread(
                bridge.set_global_hotkeys,
                True,
                {"toggle_power": "Ctrl+Alt+P", "toggle_ambilight": "Ctrl+Alt+A"},
            )
            assert saved["ok"] is True
            assert saved["global_hotkeys"]["enabled"] is True
            assert saved["global_hotkeys_supported"] is True
            assert saved["global_hotkey_errors"] == {"toggle_ambilight": "in_use"}

            restarted = LightControlService(
                controller=WizUdpController(probe_candidates=[]),
                settings_repository=JsonSettingsRepository(data_dir=tmp_path),
            )
            assert restarted.get_global_hotkeys()["enabled"] is True

            # Run host hotkey callbacks off pytest's event loop so FakeWizBulbServer answers UDP.
            initial_state = bool(server.pilot_state["state"])
            await asyncio.to_thread(app.on_global_hotkey, "toggle_power")
            assert bool(server.pilot_state["state"]) is (not initial_state)

            server.pilot_state["state"] = True
            server.pilot_state["dimming"] = 80
            await asyncio.to_thread(bridge.refresh_states)
            await asyncio.to_thread(app.on_global_hotkey, "brightness_down")
            assert int(server.pilot_state["dimming"]) == 70

            # Host-only hotkey methods stay off JsApi.
            js_api = JsApi(bridge)
            assert hasattr(js_api, "set_global_hotkeys")
            assert not hasattr(js_api, "trigger_global_hotkey")
            assert not hasattr(js_api, "set_global_hotkey_runtime")
        finally:
            hotkey_mgr.stop()
            bridge.shutdown()
