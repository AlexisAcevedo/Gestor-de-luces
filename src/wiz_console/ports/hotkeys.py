"""Driven port for OS-level global keyboard shortcut registration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class GlobalHotkeyManager(Protocol):
    """Registers and dispatches system-wide keyboard shortcuts on supported platforms."""

    def is_supported(self) -> bool:
        """Return True when global hotkey registration is supported on this host."""
        ...

    def start(self, on_trigger: Callable[[str], None]) -> None:
        """Start the listener loop, invoking `on_trigger(action_id)` on hotkey press."""
        ...

    def apply_config(self, *, enabled: bool, bindings: dict[str, str]) -> dict[str, str]:
        """Register or clear hotkeys cleanly; return per-action error codes for failures."""
        ...

    def stop(self) -> None:
        """Unregister all active hotkeys and stop the background listener cleanly."""
        ...
