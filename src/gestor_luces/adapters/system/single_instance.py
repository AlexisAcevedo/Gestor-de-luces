"""Single-instance guard for Windows built on a named mutex and a named event.

The first process owns the mutex and listens on the event. A second launch (for
example autostart plus a manual start) signals the event and exits, so the running
instance can bring its window to the front.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import sys
import threading

_LOGGER = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT_MS = 500
MUTEX_NAME = "Local\\GestorDeLuces.SingleInstance"
EVENT_NAME = "Local\\GestorDeLuces.ShowWindow"


class SingleInstanceGuard:
    """Named-mutex guard; a no-op (always primary) on non-Windows platforms."""

    def __init__(self, mutex_name: str = MUTEX_NAME, event_name: str = EVENT_NAME) -> None:
        self._mutex_name = mutex_name
        self._event_name = event_name
        self._mutex: int | None = None
        self._event: int | None = None
        self._stop = threading.Event()
        self._is_primary = True

    @property
    def is_primary(self) -> bool:
        return self._is_primary

    def acquire(self) -> bool:
        """Return True when this process is the only instance."""
        if sys.platform != "win32":
            return True
        import ctypes

        class _SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [
                ("nLength", ctypes.c_uint32),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", ctypes.c_int),
            ]

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.c_int

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateEventW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_wchar_p,
        ]
        kernel32.CreateEventW.restype = ctypes.c_void_p
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        # SDDL restringida a SYSTEM (SY), Administradores (BA) y propietario (OW).
        sddl = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;OW)"
        sd_ptr = ctypes.c_void_p()
        sa_ref = None
        if advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(sd_ptr), None
        ):
            sa = _SECURITY_ATTRIBUTES(
                ctypes.sizeof(_SECURITY_ATTRIBUTES),
                sd_ptr.value,
                0,
            )
            sa_ref = ctypes.byref(sa)

        try:
            self._mutex = kernel32.CreateMutexW(sa_ref, False, self._mutex_name)
            already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
            self._event = kernel32.CreateEventW(sa_ref, False, False, self._event_name)
        finally:
            if sd_ptr.value:
                kernel32.LocalFree(sd_ptr)

        self._is_primary = not already_running
        return self._is_primary

    def signal_existing_instance(self) -> None:
        """Ask the running instance to show its window."""
        if sys.platform != "win32" or self._event is None:
            return
        import ctypes

        ctypes.windll.kernel32.SetEvent(ctypes.c_void_p(self._event))

    def listen(self, on_show_requested: Callable[[], None]) -> None:
        """Start a daemon thread that invokes the callback when a second launch signals."""
        if sys.platform != "win32" or self._event is None or not self._is_primary:
            return
        import ctypes

        handle = ctypes.c_void_p(self._event)

        def _worker() -> None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            while not self._stop.is_set():
                if kernel32.WaitForSingleObject(handle, WAIT_TIMEOUT_MS) == WAIT_OBJECT_0:
                    try:
                        on_show_requested()
                    except Exception:
                        _LOGGER.exception("Show-window request from a second launch failed.")

        threading.Thread(target=_worker, name="GestorLucesSingleInstance", daemon=True).start()

    def release(self) -> None:
        self._stop.set()
