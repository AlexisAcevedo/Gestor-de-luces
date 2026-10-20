"""Gestor de temporizador de apagado (Sleep Timer) con atenuacion progresiva.

Permite programar el apagado automatico de los focos seleccionados tras una cuenta
regresiva asincrona. Durante el ultimo 30% del tiempo total, reduce gradualmente
el brillo hacia el minimo soportado por el firmware WiZ (10%) antes de enviar el
comando de apagado final, proporcionando una transicion visual suave para el usuario
antes de que la habitacion quede a oscuras.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Generator
import math
from typing import Any


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
        if duration_seconds <= 0:
            raise ValueError("Sleep timer duration must be greater than zero seconds.")

        self.cancel()

        loop = asyncio.get_running_loop()
        self._loop = loop
        self._active = True
        self._total_seconds = float(duration_seconds)
        self._deadline = loop.time() + self._total_seconds
        self._target_ips = list(target_ips)

        start_b = max(10, min(100, int(initial_brightness)))
        self._task = loop.create_task(
            self._run_countdown(
                duration_seconds=self._total_seconds,
                target_ips=list(self._target_ips),
                initial_brightness=start_b,
                on_step_brightness=on_step_brightness,
                on_expire_power_off=on_expire_power_off,
            ),
            name="GestorLucesSleepTimer",
        )
        return self.get_status()

    def cancel(self) -> AwaitableStatusDict:
        """Cancela inmediatamente el temporizador activo sin apagar los focos."""
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
                target_b = max(10, min(100, round(10 + span * ratio)))
                if target_ips:
                    await on_step_brightness(target_b, list(target_ips))
                if step_interval > 0:
                    await asyncio.sleep(step_interval)

            if target_ips:
                await on_expire_power_off(list(target_ips))
        except asyncio.CancelledError:
            raise
        finally:
            self._active = False
            self._total_seconds = 0.0
            self._deadline = 0.0
            self._target_ips = []
