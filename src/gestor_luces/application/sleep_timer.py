"""Gestor de temporizador de apagado (Sleep Timer) con atenuacion progresiva.

Permite programar el apagado automatico de los focos seleccionados tras una cuenta
regresiva asincrona. Durante el ultimo 30% del tiempo total, reduce gradualmente
el brillo hacia el minimo soportado por el firmware WiZ (10%) antes de enviar el
comando de apagado final, proporcionando una transicion visual suave para el usuario
antes de que la habitacion quede a oscuras.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Generator
from typing import Any


def require_finite_float(value: object, name: str) -> float:
    """Parse a numeric value into a finite float, rejecting bool, NaN, and Inf."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number, got bool.")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite number, got {value!r}.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be a finite number, got {value!r}.")
    return parsed


def require_int_value(value: object, name: str) -> int:
    """Parse an integer value while rejecting booleans and non-finite floats."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, got bool.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be a finite integer, got {value!r}.")
    try:
        return int(value)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}.") from exc


def finite_metric(value: object) -> float:
    """Return a finite float metric or 0.0 when NaN, Inf, or non-numeric."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = float(value)
        if math.isfinite(parsed):
            return parsed
    return 0.0


def sanitize_brightness(value: object, fallback: int) -> int:
    """Clamp finite numeric brightness to [10, 100], falling back on NaN/Inf/bool."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = float(value)
        if math.isfinite(parsed):
            return max(10, min(100, int(round(parsed))))
    return fallback


class AwaitableStatusDict(dict[str, Any]):
    """Diccionario de estado compatible tanto con llamadas sincronas como con `await`.

    Dado que el inicio y la cancelacion del temporizador solo requieren registrar o
    cancelar una tarea en el bucle `asyncio` activo, devolver un `dict` que tambien
    implementa `__await__` permite consumir el resultado directamente o esperarlo
    dentro de corrutinas sin romper la serializacion JSON estandar.
    """

    def __await__(self) -> Generator[Any, None, dict[str, Any]]:
        async def _resolve() -> dict[str, Any]:
            return dict(self)

        return _resolve().__await__()


class SleepTimerManager:
    """Coordina la cuenta regresiva asincrona y la atenuacion progresiva previa al apagado."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active: bool = False
        self._generation: int = 0
        self._total_seconds: float = 0.0
        self._deadline: float = 0.0
        self._target_ips: list[str] = []

    def start(
        self,
        duration_seconds: float,
        target_ips: list[str],
        initial_brightness: int,
        on_step_brightness: Callable[[int, list[str]], Awaitable[Any]],
        on_expire_power_off: Callable[[list[str]], Awaitable[Any]],
    ) -> AwaitableStatusDict:
        """Inicia una nueva cuenta regresiva cancelando cualquier temporizador previo."""
        parsed_duration = require_finite_float(duration_seconds, "Sleep timer duration")
        if parsed_duration <= 0:
            raise ValueError("Sleep timer duration must be greater than zero seconds.")
        start_b = max(10, min(100, require_int_value(initial_brightness, "initial_brightness")))
        loop = asyncio.get_running_loop()

        self.cancel()

        self._generation += 1
        run_id = self._generation
        self._loop = loop
        self._active = True
        self._total_seconds = parsed_duration
        self._deadline = loop.time() + self._total_seconds
        self._target_ips = list(target_ips)

        self._task = loop.create_task(
            self._run_countdown(
                run_id=run_id,
                duration_seconds=self._total_seconds,
                target_ips=list(self._target_ips),
                initial_brightness=start_b,
                on_step_brightness=on_step_brightness,
                on_expire_power_off=on_expire_power_off,
            ),
            name="WizConsoleSleepTimer",
        )
        return self.get_status()

    def cancel(self) -> AwaitableStatusDict:
        """Cancela inmediatamente el temporizador activo sin apagar los focos."""
        self._generation += 1
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._active = False
        self._total_seconds = 0.0
        self._deadline = 0.0
        self._target_ips = []
        return self.get_status()

    def get_status(self) -> AwaitableStatusDict:
        """Devuelve el estado actual de la cuenta regresiva para la interfaz de usuario."""
        if not self._active or self._task is None or self._task.done():
            self._active = False
            return AwaitableStatusDict(
                {
                    "active": False,
                    "remaining_seconds": 0,
                    "total_seconds": 0,
                    "target_ips": [],
                }
            )

        now = self._loop.time() if self._loop is not None else 0.0
        remaining = max(0.0, self._deadline - now)
        if remaining <= 0.0:
            return AwaitableStatusDict(
                {
                    "active": False,
                    "remaining_seconds": 0,
                    "total_seconds": 0,
                    "target_ips": [],
                }
            )

        return AwaitableStatusDict(
            {
                "active": True,
                "remaining_seconds": max(1, math.ceil(remaining)),
                "total_seconds": max(1, round(self._total_seconds)),
                "target_ips": list(self._target_ips),
            }
        )

    async def _run_countdown(
        self,
        run_id: int,
        duration_seconds: float,
        target_ips: list[str],
        initial_brightness: int,
        on_step_brightness: Callable[[int, list[str]], Awaitable[Any]],
        on_expire_power_off: Callable[[list[str]], Awaitable[Any]],
    ) -> None:
        """Ejecuta la fase estable (70%) seguida de la atenuacion en 3 pasos (30%) y el apagado."""
        try:
            steady_seconds = duration_seconds * 0.70
            fade_seconds = duration_seconds * 0.30
            steps = 3
            step_interval = fade_seconds / steps

            if steady_seconds > 0:
                await asyncio.sleep(steady_seconds)

            # Calculamos 3 escalones decrecientes desde el brillo inicial hasta el minimo de 10%
            span = max(0, initial_brightness - 10)
            step_ratios = (0.65, 0.35, 0.0)
            for ratio in step_ratios:
                if self._generation != run_id:
                    return
                target_b = max(10, min(100, round(10 + span * ratio)))
                if target_ips:
                    await on_step_brightness(target_b, list(target_ips))
                if step_interval > 0:
                    await asyncio.sleep(step_interval)

            if self._generation != run_id:
                return
            if target_ips:
                await on_expire_power_off(list(target_ips))
        except asyncio.CancelledError:
            raise
        finally:
            if self._generation == run_id:
                self._task = None
                self._active = False
                self._total_seconds = 0.0
                self._deadline = 0.0
                self._target_ips = []
