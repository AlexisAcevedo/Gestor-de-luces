"""`AutostartManager` adapter backed by the per-user Windows `Run` registry key.

HKCU needs no elevation and is removed cleanly by the uninstaller. The registry
module is injectable so tests never touch the real registry.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_VALUE_NAME = "WizConsole"
LEGACY_VALUE_NAME = "GestorDeLuces"
MINIMIZED_FLAG = "--minimized"
_CONTROL_CHARS = ("\x00", "\r", "\n")


def _validate_executable_path(executable: str) -> str:
    """Ensure the executable path is non-empty and free of quotes or control chars."""
    if not isinstance(executable, str):
        raise ValueError("Autostart executable path must be a string.")
    cleaned = executable.strip()
    if not cleaned or '"' in cleaned or any(ch in cleaned for ch in _CONTROL_CHARS):
        raise ValueError("Invalid autostart executable path.")
    return cleaned


def build_autostart_command(
    *,
    frozen: bool | None = None,
    executable: str | None = None,
) -> str:
    """Return the command line registered for autostart; it always ends with `--minimized`.

    Frozen (PyInstaller) builds register the executable itself. In development the
    window-less `pythonw.exe` sibling of the interpreter runs `-m wiz_console.main`.
    """
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    raw_exe = executable if executable is not None else sys.executable
    exe = _validate_executable_path(raw_exe)
    if is_frozen:
        return f'"{exe}" {MINIMIZED_FLAG}'
    pythonw = Path(exe).with_name("pythonw.exe")
    interpreter = _validate_executable_path(str(pythonw)) if pythonw.is_file() else exe
    return f'"{interpreter}" -m wiz_console.main {MINIMIZED_FLAG}'


class WindowsRegistryAutostart:
    """Stores the autostart command under HKCU\\...\\Run."""

    def __init__(
        self,
        *,
        registry: Any = None,
        value_name: str = DEFAULT_VALUE_NAME,
        command_factory: Any = None,
    ) -> None:
        if not isinstance(value_name, str):
            raise ValueError("Registry value name must be a string.")
        cleaned_name = value_name.strip()
        if (
            not cleaned_name
            or "\\" in cleaned_name
            or any(ch in cleaned_name for ch in _CONTROL_CHARS)
        ):
            raise ValueError("Invalid autostart registry value name.")
        if registry is None:
            import winreg

            registry = winreg
        self._reg = registry
        self._value_name = cleaned_name
        self._command_factory = command_factory or build_autostart_command

    def _read_value(self, value_name: str) -> str | None:
        try:
            with self._reg.OpenKey(
                self._reg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, self._reg.KEY_READ
            ) as key:
                value, kind = self._reg.QueryValueEx(key, value_name)
        except FileNotFoundError:
            return None
        if kind != self._reg.REG_SZ or not isinstance(value, str) or not value.strip():
            return None
        return value

    def _read(self) -> str | None:
        return self._read_value(self._value_name)

    def _delete_value(self, value_name: str) -> None:
        try:
            with self._reg.OpenKey(
                self._reg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, self._reg.KEY_SET_VALUE
            ) as key:
                self._reg.DeleteValue(key, value_name)
        except FileNotFoundError:
            return

    def registered_command(self) -> str | None:
        """Return the command currently stored in the registry, if any."""
        return self._read()

    def is_enabled(self) -> bool:
        return self._read() is not None

    def enable(self) -> None:
        command = self._command_factory()
        if (
            not isinstance(command, str)
            or not command.strip()
            or any(ch in command for ch in _CONTROL_CHARS)
        ):
            raise ValueError("Invalid autostart command.")
        with self._reg.CreateKeyEx(
            self._reg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, self._reg.KEY_SET_VALUE
        ) as key:
            self._reg.SetValueEx(key, self._value_name, 0, self._reg.REG_SZ, command)

    def disable(self) -> None:
        self._delete_value(self._value_name)
        if self._value_name == DEFAULT_VALUE_NAME:
            with_legacy_cleanup_err = False
            try:
                self._delete_value(LEGACY_VALUE_NAME)
            except OSError:
                with_legacy_cleanup_err = True
            if with_legacy_cleanup_err:
                _LOGGER.debug("Failed to remove legacy autostart entry.", exc_info=True)

    def refresh_if_stale(self) -> bool:
        """Refresh stale executable paths and migrate the legacy GestorDeLuces entry."""
        try:
            current = self._read()
        except OSError:
            _LOGGER.debug("Failed to read autostart entry during refresh.", exc_info=True)
            return False

        if current is None:
            if self._value_name != DEFAULT_VALUE_NAME:
                return False
            try:
                legacy = self._read_value(LEGACY_VALUE_NAME)
            except OSError:
                _LOGGER.debug("Failed to read legacy autostart entry.", exc_info=True)
                return False
            if legacy is None:
                return False
            try:
                self.enable()
                self._delete_value(LEGACY_VALUE_NAME)
            except OSError:
                _LOGGER.exception("Failed to migrate legacy autostart entry.")
                return False
            _LOGGER.info(
                "Migrated Windows autostart entry from '%s' to '%s'.",
                LEGACY_VALUE_NAME,
                self._value_name,
            )
            return True

        if self._value_name == DEFAULT_VALUE_NAME:
            try:
                if self._read_value(LEGACY_VALUE_NAME) is not None:
                    self._delete_value(LEGACY_VALUE_NAME)
            except OSError:
                _LOGGER.debug("Failed to clean up redundant legacy autostart entry.", exc_info=True)

        expected = self._command_factory()
        if current == expected:
            return False
        try:
            self.enable()
        except OSError:
            _LOGGER.exception("Failed to refresh the stale autostart entry.")
            return False
        return True
