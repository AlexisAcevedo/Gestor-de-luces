"""Async crossfade transition engine with per-bulb preemption and instant bypass."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any

from wiz_console.domain.value_objects import Color

MAX_TRANSITION_SECONDS = 5.0
_DEFAULT_STEP_INTERVAL = 0.05


def normalize_transition_seconds(raw: Any) -> float:
    """Validate transition duration in seconds `[0.0, 5.0]` rejecting bools and NaN/Inf."""
    if isinstance(raw, bool):
        raise ValueError("transition_seconds must be a finite number between 0.0 and 5.0.")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("transition_seconds must be a finite number between 0.0 and 5.0.") from exc
    if not math.isfinite(value) or not (0.0 <= value <= MAX_TRANSITION_SECONDS):
        raise ValueError("transition_seconds must be between 0.0 and 5.0.")
    return round(value, 2)


def ease_in_out(progress: float) -> float:
    """Smoothstep ease-in-out curve clamped to `[0.0, 1.0]`."""
    p = max(0.0, min(1.0, float(progress)))
    return p * p * (3.0 - 2.0 * p)


def interpolate_rgb(start: Color, end: Color, progress: float) -> Color:
    """Linearly interpolate two RGB `Color` values with ease-in-out progression."""
    t = ease_in_out(progress)
    return Color(
        r=max(0, min(255, round(start.r + (end.r - start.r) * t))),
        g=max(0, min(255, round(start.g + (end.g - start.g) * t))),
        b=max(0, min(255, round(start.b + (end.b - start.b) * t))),
    )


def interpolate_kelvin(start: int, end: int, progress: float) -> int:
    """Interpolate Kelvin color temperature `[2200, 6500]` with ease-in-out progression."""
    t = ease_in_out(progress)
    return max(2200, min(6500, round(start + (end - start) * t)))


def interpolate_brightness(start: int, end: int, progress: float) -> int:
    """Interpolate brightness percentage `[10, 100]` with ease-in-out progression."""
    t = ease_in_out(progress)
    return max(10, min(100, round(start + (end - start) * t)))


class TransitionEngine:
    """Coordinates smooth per-bulb color and Kelvin fades on the shared asyncio loop."""

    def __init__(self, step_interval: float | None = None) -> None:
        self._step_interval = step_interval
        self._active_tasks: dict[str, asyncio.Task[bool]] = {}

    def cancel_bulb(self, ip: str) -> None:
        """Preempt any in-flight transition running for `ip`."""
        task = self._active_tasks.pop(ip, None)
        if task is not None and not task.done():
            task.cancel()

    def cancel_all(self) -> None:
        """Cancel every active per-bulb transition across all fixtures."""
        for task in list(self._active_tasks.values()):
            if not task.done():
                task.cancel()
        self._active_tasks.clear()

    async def _run_stepped_fade(
        self,
        ip: str,
        duration_s: float,
        step_fn: Callable[[float], Awaitable[bool]],
    ) -> bool:
        steps = max(2, min(40, round(duration_s / _DEFAULT_STEP_INTERVAL)))
        interval = (
            self._step_interval if self._step_interval is not None else duration_s / float(steps)
        )

        async def _worker() -> bool:
            last_ok = True
            for idx in range(1, steps + 1):
                progress = idx / float(steps)
                last_ok = await step_fn(progress)
                if not last_ok:
                    return False
                if idx < steps:
                    await asyncio.sleep(interval)
            return last_ok

        self.cancel_bulb(ip)
        task = asyncio.create_task(_worker(), name=f"WizConsoleFade-{ip}")
        self._active_tasks[ip] = task
        try:
            return await task
        except asyncio.CancelledError:
            return True
        finally:
            if self._active_tasks.get(ip) is task:
                self._active_tasks.pop(ip, None)

    async def transition_color(
        self,
        *,
        ip: str,
        start_color: Color | None,
        start_brightness: int,
        target_color: Color,
        target_brightness: int | None,
        duration_s: float,
        apply_fn: Callable[[Color, int | None], Awaitable[bool]],
    ) -> bool:
        """Transition a bulb to `target_color` or apply immediately when `duration_s <= 0`."""
        if duration_s <= 0.0 or start_color is None:
            self.cancel_bulb(ip)
            return await apply_fn(target_color, target_brightness)

        async def _step(progress: float) -> bool:
            step_color = interpolate_rgb(start_color, target_color, progress)
            step_bri = (
                interpolate_brightness(start_brightness, target_brightness, progress)
                if target_brightness is not None
                else None
            )
            return await apply_fn(step_color, step_bri)

        return await self._run_stepped_fade(ip, duration_s, _step)

    async def transition_temperature(
        self,
        *,
        ip: str,
        start_kelvin: int | None,
        start_brightness: int,
        target_kelvin: int,
        target_brightness: int | None,
        duration_s: float,
        apply_fn: Callable[[int, int | None], Awaitable[bool]],
    ) -> bool:
        """Transition a bulb to `target_kelvin` or apply immediately when `duration_s <= 0`."""
        if duration_s <= 0.0 or start_kelvin is None:
            self.cancel_bulb(ip)
            return await apply_fn(target_kelvin, target_brightness)

        async def _step(progress: float) -> bool:
            step_temp = interpolate_kelvin(start_kelvin, target_kelvin, progress)
            step_bri = (
                interpolate_brightness(start_brightness, target_brightness, progress)
                if target_brightness is not None
                else None
            )
            return await apply_fn(step_temp, step_bri)

        return await self._run_stepped_fade(ip, duration_s, _step)
