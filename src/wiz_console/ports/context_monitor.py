"""Primary port for local-only foreground application and mic/camera context sensing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ContextSnapshot:
    """Point-in-time host context sampled locally without screen/audio recording."""

    foreground_process: str | None = None
    mic_active: bool = False
    camera_active: bool = False


@runtime_checkable
class ContextMonitor(Protocol):
    """Port implemented by OS context readers (foreground window exe + ConsentStore)."""

    def is_supported(self) -> bool:
        """Return True when context monitoring is supported on this platform."""
        ...

    def sample(self) -> ContextSnapshot:
        """Sample foreground executable basename and local mic/camera activity."""
        ...
