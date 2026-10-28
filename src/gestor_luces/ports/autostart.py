"""Driven port for the "start with Windows" preference."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AutostartManager(Protocol):
    """Registers or removes the application from the operating system's login items."""

    def is_enabled(self) -> bool:
        """Return True when an autostart entry for this application exists."""
        ...

    def enable(self) -> None:
        """Create or overwrite the autostart entry using the current executable."""
        ...

    def disable(self) -> None:
        """Remove the autostart entry; a missing entry is not an error."""
        ...

    def refresh_if_stale(self) -> bool:
        """Rewrite the entry when enabled but pointing to another path; return True if rewritten."""
        ...
