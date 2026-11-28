"""Single-instance guard for Windows built on a named mutex and a named event.

The first process owns the mutex and listens on the event. A second launch (for
example autostart plus a manual start) signals the event and exits, so the running
instance can bring its window to the front.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_FAILED = 0xFFFFFFFF
WAIT_TIMEOUT_MS = 500
MUTEX_NAME = "Local\\WizConsole.SingleInstance"
EVENT_NAME = "Local\\WizConsole.ShowWindow"


def _load_kernel32() -> Any:
    """Return kernel32 with explicit 64-bit handle argtypes and restypes."""
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
    kernel32.SetEvent.argtypes = [ctypes.c_void_p]
    kernel32.SetEvent.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32


class SingleInstanceGuard:
    """Named-mutex guard; a no-op (always primary) on non-Windows platforms."""

    def __init__(self, mutex_name: str = MUTEX_NAME, event_name: str = EVENT_NAME) -> None:
        self._mutex_name = mutex_name
        self._event_name = event_name
        self._lock = threading.Lock()
        self._mutex: int | None = None
        self._event: int | None = None
        self._listener_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._is_primary = True

    @property
    def is_primary(self) -> bool:
        return self._is_primary

    def acquire(self) -> bool:
        """Return True when this process is the only instance."""
        if sys.platform != "win32":
            return True
        with self._lock:
            if self._mutex is not None or self._event is not None:
                return self._is_primary

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

        kernel32 = _load_kernel32()

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
            mutex = kernel32.CreateMutexW(sa_ref, False, self._mutex_name)
            last_error = ctypes.get_last_error()
            already_running = last_error == ERROR_ALREADY_EXISTS or (
                not mutex and last_error == ERROR_ACCESS_DENIED
            )
            if not mutex and not already_running:
                _LOGGER.debug("CreateMutexW failed with last_error=%s.", last_error)
            event = kernel32.CreateEventW(sa_ref, False, False, self._event_name)
        finally:
            if sd_ptr.value:
                kernel32.LocalFree(sd_ptr)

        with self._lock:
            self._mutex = int(mutex) if mutex else None
            self._event = int(event) if event else None
            self._is_primary = not already_running
            return self._is_primary

    def signal_existing_instance(self) -> None:
        """Ask the running instance to show its window."""
        if sys.platform != "win32":
            return
        with self._lock:
            event = self._event
        if not event:
            return
        kernel32 = _load_kernel32()
        kernel32.SetEvent(ctypes.c_void_p(event))

    def listen(self, on_show_requested: Callable[[], None]) -> None:
        """Start a daemon thread that invokes the callback when a second launch signals."""
        if sys.platform != "win32" or not self._is_primary:
            return
        with self._lock:
            event = self._event
            if not event or (
                self._listener_thread is not None and self._listener_thread.is_alive()
            ):
                return

        handle = ctypes.c_void_p(event)

        def _worker() -> None:
            kernel32 = _load_kernel32()
            while not self._stop.is_set():
                result = kernel32.WaitForSingleObject(handle, WAIT_TIMEOUT_MS)
                if result == WAIT_OBJECT_0:
                    if self._stop.is_set():
                        break
                    try:
                        on_show_requested()
                    # FRONTERA: `on_show_requested` es el callback de la aplicacion, codigo
                    # ajeno a este modulo dentro de un hilo demonio que debe sobrevivir a
                    # cualquier fallo para seguir atendiendo el proximo segundo lanzamiento.
                    except Exception:
                        _LOGGER.exception("Show-window request from a second launch failed.")
                elif result == WAIT_FAILED:
                    _LOGGER.debug(
                        "Single-instance WaitForSingleObject failed (err=%s); stopping listener.",
                        ctypes.get_last_error(),
                    )
                    break

        thread = threading.Thread(target=_worker, name="WizConsoleSingleInstance", daemon=True)
        with self._lock:
            self._listener_thread = thread
        thread.start()

    def release(self) -> None:
        """Stop the listener thread and close owned Win32 mutex/event handles."""
        self._stop.set()
        with self._lock:
            thread = self._listener_thread
            event = self._event
            mutex = self._mutex
            self._listener_thread = None
            self._mutex = None
        if sys.platform != "win32":
            with self._lock:
                self._event = None
            return
        kernel32 = _load_kernel32()
        if thread is not None and thread.is_alive():
            if event:
                kernel32.SetEvent(ctypes.c_void_p(event))
            thread.join(timeout=2.0)
        if thread is None or not thread.is_alive():
            with self._lock:
                self._event = None
            if event:
                kernel32.CloseHandle(ctypes.c_void_p(event))
        else:
            with self._lock:
                if self._listener_thread is None:
                    self._listener_thread = thread
        if mutex:
            kernel32.CloseHandle(ctypes.c_void_p(mutex))
