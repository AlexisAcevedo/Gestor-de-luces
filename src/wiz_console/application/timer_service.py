"""Temporizador de apagado con atenuacion progresiva."""

from __future__ import annotations

from typing import Any

from wiz_console.application.bulb_control_service import BulbControlService
from wiz_console.application.service_context import ServiceContext
from wiz_console.application.sleep_timer import AwaitableStatusDict, require_finite_float


class TimerService:
    """Programa y cancela el apagado automatico de los focos objetivo."""

    def __init__(self, context: ServiceContext, bulb_control: BulbControlService) -> None:
        self._ctx = context
        self._bulb_control = bulb_control

    def start_sleep_timer(
        self,
        minutes: float,
        ips: list[str] | None = None,
    ) -> AwaitableStatusDict:
        """Programa el apagado automatico con atenuacion progresiva tras `minutes` minutos."""
        parsed_minutes = require_finite_float(minutes, "minutes")
        if parsed_minutes <= 0 or parsed_minutes > 240:
            raise ValueError("Sleep timer minutes must be greater than 0 and at most 240.")

        target_ips = self._ctx.get_target_ips(ips)
        ref_state = self._ctx.resolve_reference_state(target_ips[0] if target_ips else None)

        async def _on_step_brightness(step_b: int, step_ips: list[str]) -> None:
            await self._bulb_control.set_brightness(brightness=step_b, ips=step_ips)

        async def _on_expire_off(off_ips: list[str]) -> None:
            await self._bulb_control.set_power(is_on=False, ips=off_ips)

        return self._ctx.sleep_timer.start(
            duration_seconds=parsed_minutes * 60.0,
            target_ips=target_ips,
            initial_brightness=ref_state.brightness,
            on_step_brightness=_on_step_brightness,
            on_expire_power_off=_on_expire_off,
        )

    def cancel_sleep_timer(self) -> AwaitableStatusDict:
        """Cancela el temporizador de apagado activo."""
        return self._ctx.sleep_timer.cancel()

    def get_sleep_timer_status(self) -> dict[str, Any]:
        """Consulta el estado actual del temporizador de apagado."""
        return dict(self._ctx.sleep_timer.get_status())
