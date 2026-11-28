"""Windows session lock/unlock and sleep/resume monitor backed by Win32 messages."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import sys
import threading
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

SESSION_THREAD_NAME = "WizConsoleSessionMonitor"

WM_DESTROY = 0x0002
WM_QUIT = 0x0012
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
PM_NOREMOVE = 0x0000

PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012

WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0


def map_session_window_message(msg: int, wparam: int) -> str | None:
    """Translate Win32 session/power message constants into normalized event names."""
    if msg == WM_WTSSESSION_CHANGE:
        if wparam == WTS_SESSION_LOCK:
            return "lock"
        if wparam == WTS_SESSION_UNLOCK:
            return "unlock"
        return None
    if msg == WM_POWERBROADCAST:
        if wparam == PBT_APMSUSPEND:
            return "suspend"
        if wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
            return "resume"
        return None
    return None


class WindowsSessionMonitor:
    """Listens to `WM_WTSSESSION_CHANGE` and `WM_POWERBROADCAST` on a daemon thread."""

    def __init__(
        self,
        *,
        user32: Any | None = None,
        kernel32: Any | None = None,
        wtsapi32: Any | None = None,
        platform: str | None = None,
    ) -> None:
        self._platform = platform if platform is not None else sys.platform
        if user32 is not None or kernel32 is not None or wtsapi32 is not None:
            self._user32 = user32
            self._kernel32 = kernel32
            self._wtsapi32 = wtsapi32
        elif self._platform == "win32":
            windll = getattr(ctypes, "windll", None)
            self._user32 = getattr(windll, "user32", None)
            self._kernel32 = getattr(windll, "kernel32", None)
            self._wtsapi32 = getattr(windll, "wtsapi32", None)
        else:
            self._user32 = None
            self._kernel32 = None
            self._wtsapi32 = None

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready_event: threading.Event | None = None
        self._on_event: Callable[[str], None] | None = None
        self._stopping = False

    def is_supported(self) -> bool:
        """Return True on Windows when User32/Kernel32/WTSAPI32 APIs are available."""
        return (
            self._platform == "win32"
            and self._user32 is not None
            and self._kernel32 is not None
            and self._wtsapi32 is not None
        )

    def start(self, on_event: Callable[[str], None]) -> None:
        """Start the dedicated session/power monitor thread if supported."""
        ready_event: threading.Event | None = None
        with self._lock:
            self._on_event = on_event
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
                name=SESSION_THREAD_NAME,
                daemon=True,
            )
            self._thread = thread
            thread.start()

        if ready_event is not None:
            ready_event.wait(timeout=2.0)

    def stop(self) -> None:
        """Post `WM_QUIT`, unregister WTS notifications, and join the monitor thread."""
        with self._lock:
            self._stopping = True
            thread = self._thread
            thread_id = self._thread_id

        if thread_id is not None and self._user32 is not None:
            try:
                self._user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:
                _LOGGER.debug("Failed to post WM_QUIT to session monitor thread.", exc_info=True)

        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2.0)

        with self._lock:
            self._thread = None
            self._thread_id = None

    def _create_listener_window(self) -> Any:
        create_fn = getattr(self._user32, "CreateWindowExW", None)
        if not callable(create_fn):
            return None
        get_module = getattr(self._kernel32, "GetModuleHandleW", None)
        hinstance = get_module(None) if callable(get_module) else None
        # Hidden unshown window receives broadcast WM_POWERBROADCAST and WTS notifications.
        return create_fn(
            0,
            "Static",
            "WizConsoleSessionMonitorWindow",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )

    def _pump_loop(self, ready_event: threading.Event) -> None:
        msg = wintypes.MSG()
        hwnd: Any = None
        registered_wts = False
        try:
            thread_id = int(self._kernel32.GetCurrentThreadId())
            self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
            hwnd = self._create_listener_window()
            if hwnd and self._wtsapi32 is not None:
                register_fn = getattr(self._wtsapi32, "WTSRegisterSessionNotification", None)
                if callable(register_fn):
                    registered_wts = bool(register_fn(hwnd, NOTIFY_FOR_THIS_SESSION))

            with self._lock:
                self._thread_id = thread_id
                stopping_already = self._stopping
            ready_event.set()
            if stopping_already:
                return

            translate_fn = getattr(self._user32, "TranslateMessage", None)
            dispatch_fn = getattr(self._user32, "DispatchMessageW", None)
            while True:
                res = int(self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0))
                if res <= 0:
                    break
                event = map_session_window_message(int(msg.message), int(msg.wParam))
                if event is not None:
                    self._dispatch_event(event)
                if callable(translate_fn):
                    translate_fn(ctypes.byref(msg))
                if callable(dispatch_fn):
                    dispatch_fn(ctypes.byref(msg))
        except Exception:
            _LOGGER.exception("Windows session monitor pump terminated unexpectedly.")
            ready_event.set()
        finally:
            if registered_wts and hwnd and self._wtsapi32 is not None:
                unregister_fn = getattr(self._wtsapi32, "WTSUnRegisterSessionNotification", None)
                if callable(unregister_fn):
                    try:
                        unregister_fn(hwnd)
                    except Exception:
                        _LOGGER.debug("Failed to unregister WTS notification.", exc_info=True)
            if hwnd and self._user32 is not None:
                destroy_fn = getattr(self._user32, "DestroyWindow", None)
                if callable(destroy_fn):
                    try:
                        destroy_fn(hwnd)
                    except Exception:
                        _LOGGER.debug("Failed to destroy session listener window.", exc_info=True)
            with self._lock:
                self._thread_id = None

    def _dispatch_event(self, event: str) -> None:
        with self._lock:
            callback = self._on_event
            stopping = self._stopping
        if stopping or callback is None:
            return
        try:
            callback(event)
        # FRONTERA: runs inside Win32 message thread; callback error must never kill pump.
        except Exception:
            _LOGGER.exception("Session trigger handler failed for event %r.", event)
