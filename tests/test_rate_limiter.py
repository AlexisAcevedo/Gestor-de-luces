"""Pruebas unitarias para el limitador de frecuencia y filtro EMA (StreamRateLimiter)."""

from __future__ import annotations

import pytest

from wiz_console.application.rate_limiter import StreamRateLimiter
from wiz_console.domain.value_objects import Color


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


def test_rate_limiter_small_alpha_does_not_stall_in_deadband() -> None:
    """Con alpha chico y deadband activo, el EMA interno avanza sin estancarse."""
    clock = FakeClock()
    limiter = StreamRateLimiter(
        max_hz=10.0,
        alpha=0.05,
        min_color_delta=3,
        min_brightness_delta=3,
        clock=clock,
    )

    assert limiter.prepare_frame("192.168.1.38", Color(0, 0, 0), 20) == (Color(0, 0, 0), 20)

    emitted: list[tuple[Color, int]] = []
    for _ in range(120):
        clock.advance(0.15)
        res = limiter.prepare_frame("192.168.1.38", Color(40, 0, 0), 50)
        if res is not None:
            emitted.append(res)

    assert len(emitted) >= 3
    last_color, last_brightness = emitted[-1]
    assert last_color.r >= 38
    assert last_brightness >= 48


@pytest.mark.parametrize("bad_float", [float("nan"), float("inf"), float("-inf"), True, False])
def test_rate_limiter_rejects_non_finite_and_bool_params(bad_float: object) -> None:
    """Rechaza NaN, Inf y booleanos en max_hz, alpha y umbrales."""
    with pytest.raises(ValueError):
        StreamRateLimiter(max_hz=bad_float)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        StreamRateLimiter(alpha=bad_float)  # type: ignore[arg-type]

    limiter = StreamRateLimiter()
    with pytest.raises(ValueError):
        limiter.set_alpha(bad_float)  # type: ignore[arg-type]

    if isinstance(bad_float, bool):
        with pytest.raises(ValueError):
            StreamRateLimiter(min_color_delta=bad_float)
        with pytest.raises(ValueError):
            StreamRateLimiter(min_brightness_delta=bad_float)
