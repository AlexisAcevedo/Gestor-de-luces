"""Windows foreground process and local ConsentStore mic/camera context adapter."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import sys
from typing import Any

from wiz_console.ports.context_monitor import ContextSnapshot

if sys.platform == "win32":
    import winreg
else:  # pragma: no cover - non-Windows import guard
    winreg = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_CONSENT_BASE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"


class WindowsContextMonitor:
    """Samples Windows foreground executable basename and ConsentStore mic/camera usage."""

    def __init__(
        self,
        *,
        user32: Any | None = None,
        kernel32: Any | None = None,
        winreg_module: Any | None = None,
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
        self._winreg = winreg_module if winreg_module is not None else winreg

    def is_supported(self) -> bool:
        """Return True on Windows when User32/Kernel32 APIs are available."""
        return self._platform == "win32" and self._user32 is not None and self._kernel32 is not None

    def sample(self) -> ContextSnapshot:
        """Return current foreground executable basename and mic/camera usage flags."""
        if not self.is_supported():
            return ContextSnapshot()
        return ContextSnapshot(
            foreground_process=self._read_foreground_process(),
            mic_active=self._is_capability_active("microphone"),
            camera_active=self._is_capability_active("webcam"),
        )

    def _read_foreground_process(self) -> str | None:
        try:
            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return None
            pid = wintypes.DWORD(0)
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return None
            handle = self._kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION,
                False,
                int(pid.value),
            )
            if not handle:
                return None
            try:
                buf = ctypes.create_unicode_buffer(512)
                size = wintypes.DWORD(len(buf))
                ok = self._kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
                if not ok or not buf.value:
                    return None
                return os.path.basename(buf.value).lower()
            finally:
                self._kernel32.CloseHandle(handle)
        except Exception:
            _LOGGER.debug("Foreground process inspection skipped.", exc_info=True)
            return None

    def _is_capability_active(self, capability: str) -> bool:
        if self._winreg is None:
            return False
        root = getattr(self._winreg, "HKEY_CURRENT_USER", None)
        if root is None:
            return False
        base_path = f"{_CONSENT_BASE}\\{capability}"
        return self._scan_consent_branch(root, base_path) or self._scan_consent_branch(
            root, f"{base_path}\\NonPackaged"
        )

    def _scan_consent_branch(self, root: Any, subkey_path: str) -> bool:
        try:
            with self._winreg.OpenKey(root, subkey_path) as parent_key:
                index = 0
                while True:
                    try:
                        child_name = self._winreg.EnumKey(parent_key, index)
                    except OSError:
                        break
                    index += 1
                    if child_name == "NonPackaged":
                        continue
                    try:
                        with self._winreg.OpenKey(parent_key, child_name) as app_key:
                            stop_val, _ = self._winreg.QueryValueEx(app_key, "LastUsedTimeStop")
                            start_val, _ = self._winreg.QueryValueEx(app_key, "LastUsedTimeStart")
                            if int(start_val) > 0 and int(stop_val) == 0:
                                return True
                    except OSError:
                        continue
        except OSError:
            return False
        return False
