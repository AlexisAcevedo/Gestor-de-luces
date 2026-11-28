"""Windows global hotkey adapter backed by Win32 ``RegisterHotKey``."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import sys
import threading
from collections.abc import Callable
from typing import Any

from wiz_console.domain.value_objects import HOTKEY_ACTIONS, normalize_hotkey_combo

_LOGGER = logging.getLogger(__name__)

HOTKEY_THREAD_NAME = "WizConsoleHotkeys"

WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_RELOAD_HOTKEYS = WM_APP + 1
PM_NOREMOVE = 0x0000

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_MODIFIER_FLAGS: dict[str, int] = {
    "Alt": MOD_ALT,
    "Ctrl": MOD_CONTROL,
    "Shift": MOD_SHIFT,
    "Win": MOD_WIN,
}
_SPECIAL_VK_CODES: dict[str, int] = {
    "Space": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "Left": 0x25,
    "Up": 0x26,
    "Right": 0x27,
    "Down": 0x28,
}


def parse_win32_hotkey(combo: str) -> tuple[int, int]:
    """Convert a normalized hotkey string into ``(win32_modifiers, virtual_key_code)``."""
    normalized = normalize_hotkey_combo(combo)
    if not normalized:
        raise ValueError("Cannot parse an empty hotkey combination.")
    parts = normalized.split("+")
    key_token = parts[-1]
    modifiers = MOD_NOREPEAT
    for part in parts[:-1]:
        modifiers |= _MODIFIER_FLAGS[part]

    if len(key_token) == 1 and key_token.isascii() and key_token.isalnum():
        vk = ord(key_token)
    elif key_token.startswith("F") and key_token[1:].isdigit():
        fn_num = int(key_token[1:])
        vk = 0x70 + (fn_num - 1)
    elif key_token in _SPECIAL_VK_CODES:
        vk = _SPECIAL_VK_CODES[key_token]
    else:
        raise ValueError(f"Unsupported Win32 hotkey key: {key_token!r}.")

    return modifiers, vk


class WindowsGlobalHotkeyManager:
    """Manages Win32 ``RegisterHotKey`` bindings on a dedicated message-pump thread."""

    def __init__(
        self,
        *,
        user32: Any | None = None,
        kernel32: Any | None = None,
        platform: str | None = None,
    ) -> None:
        self._platform = platform if platform is not None else sys.platform
        if user32 is not None or kernel32 is not None:
            self._user32 = user32
            self._kernel32 = kernel32
        elif self._platform == "win32":
            windll = getattr(ctypes, "windll", None)
            self._user32 = getattr(windll, "user32", None)
            self._kernel32 = getattr(windll, "kernel32", None)
        else:
            self._user32 = None
            self._kernel32 = None

        self._lock = threading.Lock()
        self._sync_cond = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready_event: threading.Event | None = None
        self._on_trigger: Callable[[str], None] | None = None
        self._desired_enabled = False
        self._desired_bindings: dict[str, str] = {}
        self._config_seq = 0
        self._applied_seq = 0
        self._stopping = False
        self._registered_ids: dict[int, str] = {}
        self._last_errors: dict[str, str] = {}

    def is_supported(self) -> bool:
        """Return True on Windows when User32/Kernel32 hotkey APIs are available."""
        return self._platform == "win32" and self._user32 is not None and self._kernel32 is not None

    def start(self, on_trigger: Callable[[str], None]) -> None:
        """Start the dedicated hotkey message loop thread if supported."""
        ready_event: threading.Event | None = None
        with self._lock:
            self._on_trigger = on_trigger
            if not self.is_supported():
                return
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            ready_event = threading.Event()
            self._ready_event = ready_event
            thread = threading.Thread(
                target=self._pump_loop,
                args=(ready_event,),
                name=HOTKEY_THREAD_NAME,
                daemon=True,
            )
            self._thread = thread
            thread.start()

        if ready_event is not None:
            ready_event.wait(timeout=2.0)

    def apply_config(self, *, enabled: bool, bindings: dict[str, str]) -> dict[str, str]:
        """Apply updated hotkey bindings synchronously on the Win32 hotkey thread."""
        with self._lock:
            self._desired_enabled = bool(enabled)
            self._desired_bindings = {k: str(v) for k, v in bindings.items() if k in HOTKEY_ACTIONS}
            self._config_seq += 1
            target_seq = self._config_seq
            thread = self._thread
            thread_id = self._thread_id
            if (
                not self.is_supported()
                or thread is None
                or not thread.is_alive()
                or thread_id is None
            ):
                self._last_errors = {}
                self._applied_seq = target_seq
                self._sync_cond.notify_all()
                return {}

        posted = False
        try:
            posted = bool(self._user32.PostThreadMessageW(thread_id, WM_RELOAD_HOTKEYS, 0, 0))
        except Exception:
            _LOGGER.debug("Failed to signal hotkey reload.", exc_info=True)

        with self._lock:
            if not posted:
                return dict(self._last_errors)
            self._sync_cond.wait_for(
                lambda: (
                    self._applied_seq >= target_seq or self._stopping or self._thread_id is None
                ),
                timeout=2.0,
            )
            return dict(self._last_errors)

    def stop(self) -> None:
        """Unregister active hotkeys and join the background message loop thread cleanly."""
        with self._lock:
            self._stopping = True
            thread = self._thread
            thread_id = self._thread_id
            self._sync_cond.notify_all()

        if thread_id is not None and self._user32 is not None:
            try:
                self._user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:
                _LOGGER.debug("Failed to post WM_QUIT to hotkey thread.", exc_info=True)

        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2.0)

        with self._lock:
            self._thread = None
            self._thread_id = None
            self._registered_ids.clear()
            self._sync_cond.notify_all()

    def _pump_loop(self, ready_event: threading.Event) -> None:
        msg = wintypes.MSG()
        try:
            thread_id = int(self._kernel32.GetCurrentThreadId())
            # Force creation of a Win32 message queue before signaling readiness to callers.
            self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
            with self._lock:
                self._thread_id = thread_id
                stopping_already = self._stopping
            ready_event.set()
            if stopping_already:
                return

            self._reconcile_registrations()

            while True:
                res = int(self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0))
                if res <= 0:
                    break
                if msg.message == WM_RELOAD_HOTKEYS:
                    self._reconcile_registrations()
                elif msg.message == WM_HOTKEY:
                    self._dispatch_hotkey(int(msg.wParam))
        except Exception:
            _LOGGER.exception("Global hotkey pump terminated unexpectedly.")
            ready_event.set()
        finally:
            self._unregister_all()
            with self._lock:
                self._thread_id = None
                self._sync_cond.notify_all()

    def _unregister_all(self) -> None:
        with self._lock:
            ids = list(self._registered_ids.keys())
            self._registered_ids.clear()
        if self._user32 is None:
            return
        for hotkey_id in ids:
            try:
                self._user32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                _LOGGER.debug("UnregisterHotKey failed for id=%s.", hotkey_id, exc_info=True)

    def _reconcile_registrations(self) -> None:
        self._unregister_all()
        with self._lock:
            enabled = self._desired_enabled
            bindings = dict(self._desired_bindings)
            target_seq = self._config_seq

        errors: dict[str, str] = {}
        registered: dict[int, str] = {}

        if enabled and self._user32 is not None:
            for idx, action in enumerate(HOTKEY_ACTIONS, start=1):
                combo = bindings.get(action, "")
                if not combo:
                    continue
                try:
                    modifiers, vk = parse_win32_hotkey(combo)
                except ValueError:
                    errors[action] = "invalid_combo"
                    continue
                set_last_error = getattr(self._kernel32, "SetLastError", None)
                if callable(set_last_error):
                    set_last_error(0)
                ok = bool(self._user32.RegisterHotKey(None, idx, modifiers, vk))
                if ok:
                    registered[idx] = action
                else:
                    last_err = int(self._kernel32.GetLastError()) if self._kernel32 else 0
                    errors[action] = (
                        "in_use"
                        if last_err == ERROR_HOTKEY_ALREADY_REGISTERED
                        else "register_failed"
                    )

        with self._lock:
            self._registered_ids = registered
            self._last_errors = errors
            self._applied_seq = max(self._applied_seq, target_seq)
            self._sync_cond.notify_all()

    def _dispatch_hotkey(self, hotkey_id: int) -> None:
        with self._lock:
            action = self._registered_ids.get(hotkey_id)
            callback = self._on_trigger
        if action is None or callback is None:
            return
        try:
            callback(action)
        except Exception:
            _LOGGER.exception("Global hotkey callback failed for action '%s'.", action)
