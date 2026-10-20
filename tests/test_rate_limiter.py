"""Pruebas unitarias para el limitador de frecuencia y filtro EMA (StreamRateLimiter)."""

from __future__ import annotations

from gestor_luces.application.rate_limiter import StreamRateLimiter
from gestor_luces.domain.value_objects import Color


class FakeClock:
    """Reloj determinista para probar intervalos de tiempo sin usar sleep real."""

    def __init__(self, initial: float = 100.0) -> None:
        self.current = initial

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def test_rate_limiter_enforces_minimum_interval_per_bulb() -> None:
    """Verifica que no se emitan mas paquetes que max_hz para un mismo foco."""
    clock = FakeClock()
    limiter = StreamRateLimiter(max_hz=10.0, alpha=1.0, clock=clock)

    first = limiter.prepare_frame("192.168.1.38", Color(255, 0, 0), 100)
    assert first == (Color(255, 0, 0), 100)

    # A los 50 ms (< 100 ms requeridos para 10 Hz) debe suprimir el envio
    clock.advance(0.05)
    suppressed = limiter.prepare_frame("192.168.1.38", Color(0, 255, 0), 100)
    assert suppressed is None

    # Otro foco distinto en el mismo instante NO debe verse bloqueado
    other_bulb = limiter.prepare_frame("192.168.1.39", Color(0, 0, 255), 80)
    assert other_bulb == (Color(0, 0, 255), 80)

    # Al superar los 100 ms, el primer foco vuelve a aceptar paquetes
    clock.advance(0.06)
    allowed = limiter.prepare_frame("192.168.1.38", Color(0, 255, 0), 100)
    assert allowed == (Color(0, 255, 0), 100)


def test_rate_limiter_deduplicates_small_changes() -> None:
    """Verifica que cambios menores al umbral de delta no generen trafico UDP."""
    clock = FakeClock()
    limiter = StreamRateLimiter(
        max_hz=10.0,
        alpha=1.0,
        min_color_delta=4,
        min_brightness_delta=3,
        clock=clock,
    )

    limiter.prepare_frame("192.168.1.38", Color(100, 100, 100), 50)

    clock.advance(0.2)
    # Variacion de apenas 2 puntos en RGB y 1% en brillo: se descarta
    assert limiter.prepare_frame("192.168.1.38", Color(102, 100, 99), 51) is None

    clock.advance(0.2)
    # Variacion de 10 puntos en canal rojo: supera el umbral y se transmite
    result = limiter.prepare_frame("192.168.1.38", Color(110, 100, 100), 50)
    assert result == (Color(110, 100, 100), 50)


def test_rate_limiter_applies_ema_smoothing() -> None:
    """Comprueba que el filtro EMA suavice saltos bruscos de color y brillo."""
    clock = FakeClock()
    limiter = StreamRateLimiter(
        max_hz=10.0,
        alpha=0.5,
        min_color_delta=1,
        min_brightness_delta=1,
        clock=clock,
    )

    limiter.prepare_frame("192.168.1.38", Color(0, 0, 0), 20)

    clock.advance(0.2)
    smoothed = limiter.prepare_frame("192.168.1.38", Color(200, 100, 50), 100)
    assert smoothed == (Color(100, 50, 25), 60)
