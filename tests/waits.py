"""Esperas acotadas sobre condiciones observables, sin duraciones fijas.

Tarea T-6.3 del endurecimiento: toda espera de la suite se decide por una condicion
(estado del servicio, estado del bulbo simulado, hilo vivo) con un techo de tiempo. Un
`sleep` de duracion fija
hace lento el verde y, peor, fragil el rojo: si la maquina corre lento, el test falla sin que
haya un defecto, y si corre rapido nadie nota que la espera era innecesaria.

La cadencia de sondeo nunca decide el resultado: una corrida lenta solo sondea mas veces.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

#: Techo por defecto. Las condiciones normales se cumplen en milisegundos; el techo existe
#: para fallar rapido con un mensaje que nombra la condicion, no para acertar de casualidad.
DEFAULT_TIMEOUT_SECONDS = 10.0
#: Cadencia del sondeo.
POLL_SECONDS = 0.01


def wait_until(
    predicate: Callable[[], bool],
    description: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Espera (bloqueante) a que `predicate` sea verdadero; si no, falla con `description`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(POLL_SECONDS)
    if not predicate():
        raise AssertionError(f"{description} (within {timeout}s)")


def wait_for(
    read: Callable[[], Any],
    predicate: Callable[[Any], bool],
    description: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Sondea `read()` hasta que `predicate` lo acepte y devuelve ese ultimo valor leido."""
    deadline = time.monotonic() + timeout
    value = read()
    while time.monotonic() < deadline:
        value = read()
        if predicate(value):
            return value
        time.sleep(POLL_SECONDS)
    if not predicate(value):
        raise AssertionError(f"{description} (within {timeout}s)")
    return value


async def wait_until_async(
    predicate: Callable[[], bool],
    description: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Igual que `wait_until`, sin bloquear el bucle de eventos."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(POLL_SECONDS)
    if not predicate():
        raise AssertionError(f"{description} (within {timeout}s)")


async def wait_for_async(
    read: Callable[[], Any],
    predicate: Callable[[Any], bool],
    description: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Igual que `wait_for`, sin bloquear el bucle de eventos."""
    deadline = time.monotonic() + timeout
    value = read()
    while time.monotonic() < deadline:
        value = read()
        if predicate(value):
            return value
        await asyncio.sleep(POLL_SECONDS)
    if not predicate(value):
        raise AssertionError(f"{description} (within {timeout}s)")
    return value


async def wait_quiet_async(
    predicate: Callable[[], bool],
    description: str,
    *,
    window: float,
) -> None:
    """Verifica que `predicate` se mantenga verdadero durante `window` (asercion negativa).

    Es la unica forma honesta de fijar «esto no debe pasar»: se sondea la condicion durante
    toda la ventana en vez de dormirla, asi que un cambio se detecta en el proximo sondeo.
    """
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        if not predicate():
            raise AssertionError(f"{description} (within {window}s)")
        await asyncio.sleep(POLL_SECONDS)
    if not predicate():
        raise AssertionError(f"{description} (within {window}s)")
