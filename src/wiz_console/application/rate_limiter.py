"""Controlador de frecuencia, suavizado EMA y deduplicacion para flujos UDP continuos.

El microcontrolador ESP de los focos WiZ puede saturarse o descartar paquetes si
recibe mas de ~12 mensajes UDP por segundo de forma sostenida. Ademas, enviar el
mismo color repetidamente cuando la pantalla o el silencio no cambian desperdicia
ancho de banda WiFi 2.4 GHz. Este modulo resuelve ambos problemas en la capa de
aplicacion antes de tocar el adaptador de red.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from wiz_console.application.sleep_timer import require_finite_float, require_int_value
from wiz_console.domain.value_objects import Brightness, Color


@dataclass
class _TargetStreamState:
    """Almacena el estado EMA continuo y el ultimo estado discreto emitido para una IP."""

    last_sent_at: float
    ema_r: float
    ema_g: float
    ema_b: float
    ema_brightness: float
    emitted_color: Color
    emitted_brightness: int


class StreamRateLimiter:
    """Regula el flujo de fotogramas de color y brillo hacia cada foco por separado.

    Aplica tres filtros en cadena por cada IP destino:
    1. Límite de tasa (Rate cap): garantiza un intervalo minimo (1 / max_hz) entre envios.
    2. Suavizado exponencial (EMA): interpola el color y el brillo en punto flotante para
       que los deltas pequeños sigan acumulando avance sin quedar estancados en la banda muerta.
    3. Deduplicacion por umbral (Deadband): omite el envio si el cambio discreto respecto al
       ultimo paquete transmitido es imperceptible para el ojo humano.
    """

    def __init__(
        self,
        max_hz: float = 9.0,
        alpha: float = 0.4,
        min_color_delta: int = 3,
        min_brightness_delta: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        parsed_hz = require_finite_float(max_hz, "max_hz")
        if parsed_hz <= 0:
            raise ValueError(f"max_hz must be greater than 0, got {max_hz}.")
        parsed_alpha = require_finite_float(alpha, "alpha")
        if not (0.0 < parsed_alpha <= 1.0):
            raise ValueError(f"alpha must be in (0.0, 1.0], got {alpha}.")
        parsed_color_delta = require_int_value(min_color_delta, "min_color_delta")
        parsed_brightness_delta = require_int_value(min_brightness_delta, "min_brightness_delta")
        if parsed_color_delta < 0 or parsed_brightness_delta < 0:
            raise ValueError("Delta thresholds cannot be negative.")

        self._min_interval: float = 1.0 / parsed_hz
        self._alpha: float = parsed_alpha
        self._min_color_delta: int = parsed_color_delta
        self._min_brightness_delta: int = parsed_brightness_delta
        self._clock: Callable[[], float] = clock
        self._states: dict[str, _TargetStreamState] = {}

    @property
    def min_interval(self) -> float:
        """Devuelve el intervalo minimo en segundos permitido entre envios a un mismo foco."""
        return self._min_interval

    @property
    def alpha(self) -> float:
        """Devuelve el factor de suavizado EMA vigente en (0.0, 1.0]."""
        return self._alpha

    def set_alpha(self, alpha: float) -> None:
        """Actualiza en caliente el coeficiente EMA cuando el usuario ajusta la respuesta visual."""
        parsed = require_finite_float(alpha, "alpha")
        if not (0.0 < parsed <= 1.0):
            raise ValueError(f"alpha must be in (0.0, 1.0], got {alpha}.")
        self._alpha = parsed

    def prepare_frame(
        self,
        ip: str,
        target_color: Color,
        target_brightness: int,
    ) -> tuple[Color, int] | None:
        """Evalua si corresponde enviar un nuevo fotograma al foco indicado.

        Devuelve una tupla (color_suavizado, brillo_suavizado) lista para transmitir,
        o None si el paquete debe descartarse por limite de frecuencia o redundancia.
        """
        validated_brightness = Brightness(target_brightness).percent
        now = self._clock()
        prev = self._states.get(ip)

        if prev is None:
            self._states[ip] = _TargetStreamState(
                last_sent_at=now,
                ema_r=float(target_color.r),
                ema_g=float(target_color.g),
                ema_b=float(target_color.b),
                ema_brightness=float(validated_brightness),
                emitted_color=target_color,
                emitted_brightness=validated_brightness,
            )
            return target_color, validated_brightness

        if (now - prev.last_sent_at) < self._min_interval:
            return None

        # Avanzamos el EMA continuo antes del deadband para evitar estancamientos con alpha bajo.
        prev.ema_r += (target_color.r - prev.ema_r) * self._alpha
        prev.ema_g += (target_color.g - prev.ema_g) * self._alpha
        prev.ema_b += (target_color.b - prev.ema_b) * self._alpha
        prev.ema_brightness += (validated_brightness - prev.ema_brightness) * self._alpha

        next_color = Color(
            r=max(0, min(255, round(prev.ema_r))),
            g=max(0, min(255, round(prev.ema_g))),
            b=max(0, min(255, round(prev.ema_b))),
        )
        next_brightness = max(10, min(100, round(prev.ema_brightness)))

        color_delta = next_color.max_channel_delta(prev.emitted_color)
        brightness_delta = abs(next_brightness - prev.emitted_brightness)

        if color_delta < self._min_color_delta and brightness_delta < self._min_brightness_delta:
            return None

        prev.last_sent_at = now
        prev.emitted_color = next_color
        prev.emitted_brightness = next_brightness
        return next_color, next_brightness

    def reset(self, ip: str | None = None) -> None:
        """Reinicia el historial de suavizado y tiempos de un foco o de todos."""
        if ip is None:
            self._states.clear()
        else:
            self._states.pop(ip, None)
