"""`AutostartManager` adapter backed by the per-user Windows `Run` registry key.

HKCU needs no elevation and is removed cleanly by the uninstaller. The registry
module is injectable so tests never touch the real registry.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys
from typing import Any

_LOGGER = logging.getLogger(__name__)

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_VALUE_NAME = "GestorDeLuces"
MINIMIZED_FLAG = "--minimized"


def build_autostart_command(
    *,
    frozen: bool | None = None,
    executable: str | None = None,
) -> str:
    """Return the command line registered for autostart; it always ends with `--minimized`.

    Frozen (PyInstaller) builds register the executable itself. In development the
    window-less `pythonw.exe` sibling of the interpreter runs `-m gestor_luces.main`.
    """
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = executable if executable is not None else sys.executable
    if is_frozen:
        return f'"{exe}" {MINIMIZED_FLAG}'
    pythonw = Path(exe).with_name("pythonw.exe")
    interpreter = str(pythonw) if pythonw.is_file() else exe
    return f'"{interpreter}" -m gestor_luces.main {MINIMIZED_FLAG}'


class WindowsRegistryAutostart:
    """Stores the autostart command under HKCU\\...\\Run."""

    def __init__(
        self,
        *,
        registry: Any = None,
        value_name: str = DEFAULT_VALUE_NAME,
        command_factory: Any = None,
    ) -> None:
        if registry is None:
            import winreg

            registry = winreg
        self._reg = registry
        self._value_name = value_name
        self._command_factory = command_factory or build_autostart_command

    def _read(self) -> str | None:
        try:
            with self._reg.OpenKey(
                self._reg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, self._reg.KEY_READ
            ) as key:
                value, _kind = self._reg.QueryValueEx(key, self._value_name)
        except FileNotFoundError:
            return None
        return str(value)

    def registered_command(self) -> str | None:
        """Return the command currently stored in the registry, if any."""
        return self._read()

    def is_enabled(self) -> bool:
        return self._read() is not None

    def enable(self) -> None:
        with self._reg.CreateKeyEx(
            self._reg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, self._reg.KEY_SET_VALUE
        ) as key:
            self._reg.SetValueEx(
                key, self._value_name, 0, self._reg.REG_SZ, self._command_factory()
            )

    def disable(self) -> None:
        try:
            with self._reg.OpenKey(
                self._reg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, self._reg.KEY_SET_VALUE
            ) as key:
                self._reg.DeleteValue(key, self._value_name)
        except FileNotFoundError:
            return

    def refresh_if_stale(self) -> bool:
        """Rewrite the entry when the app moved (portable build) since it was registered."""
        current = self._read()
        if current is None:
            return False
        expected = self._command_factory()
        if current == expected:
            return False
        try:
            self.enable()
        except OSError:
            _LOGGER.exception("Failed to refresh the stale autostart entry.")
            return False
        return True
