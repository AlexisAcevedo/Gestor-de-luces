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

from gestor_luces.domain.value_objects import Brightness, Color


@dataclass
class _TargetStreamState:
    """Almacena el ultimo estado emitido y su marca de tiempo para una IP especifica."""

    last_sent_at: float
    smoothed_color: Color
    smoothed_brightness: int


class StreamRateLimiter:
    """Regula el flujo de fotogramas de color y brillo hacia cada foco por separado.

    Aplica tres filtros en cadena por cada IP destino:
    1. Límite de tasa (Rate cap): garantiza un intervalo minimo (1 / max_hz) entre envios.
    2. Suavizado exponencial (EMA): interpola el color y el brillo con el estado previo
       usando el factor alpha para evitar parpadeos desagradables.
    3. Deduplicacion por umbral (Deadband): omite el envio si el cambio respecto al
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
        if max_hz <= 0:
            raise ValueError(f"max_hz must be greater than 0, got {max_hz}.")
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"alpha must be in (0.0, 1.0], got {alpha}.")
        if min_color_delta < 0 or min_brightness_delta < 0:
            raise ValueError("Delta thresholds cannot be negative.")

        self._min_interval: float = 1.0 / max_hz
        self._alpha: float = alpha
        self._min_color_delta: int = min_color_delta
        self._min_brightness_delta: int = min_brightness_delta
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
        parsed = float(alpha)
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
                smoothed_color=target_color,
                smoothed_brightness=validated_brightness,
            )
            return target_color, validated_brightness

        if (now - prev.last_sent_at) < self._min_interval:
            return None

        # Calculamos el estado suavizado con media movil exponencial (EMA)
        next_color = prev.smoothed_color.lerp(target_color, self._alpha)
        raw_brightness = round(
            prev.smoothed_brightness
            + (validated_brightness - prev.smoothed_brightness) * self._alpha
        )
        next_brightness = max(10, min(100, raw_brightness))

        color_delta = next_color.max_channel_delta(prev.smoothed_color)
        brightness_delta = abs(next_brightness - prev.smoothed_brightness)

        if color_delta < self._min_color_delta and brightness_delta < self._min_brightness_delta:
            return None

        prev.last_sent_at = now
        prev.smoothed_color = next_color
        prev.smoothed_brightness = next_brightness
        return next_color, next_brightness

    def reset(self, ip: str | None = None) -> None:
        """Reinicia el historial de suavizado y tiempos de un foco o de todos."""
        if ip is None:
            self._states.clear()
        else:
            self._states.pop(ip, None)
