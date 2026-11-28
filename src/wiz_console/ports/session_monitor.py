"""Primary port for monitoring host OS lock/unlock and sleep/resume session events."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

SESSION_EVENTS: frozenset[str] = frozenset({"lock", "unlock", "suspend", "resume"})


@runtime_checkable
class SessionMonitor(Protocol):
    """Port implemented by OS session/power listeners (for example Win32 WTS/power)."""

    def is_supported(self) -> bool:
        """Return True when session/power notifications are available on this host."""
        ...

    def start(self, on_event: Callable[[str], None]) -> None:
        """Start background monitoring and dispatch normalized event names to `on_event`."""
        ...

    def stop(self) -> None:
        """Unregister OS notifications and join the monitor thread cleanly."""
        ...
