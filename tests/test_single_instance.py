"""Guarda de instancia unica: segunda instancia, liberacion del lock y proceso matado.

`adapters/system/single_instance.py` no tenia tests (T-6.1). El contrato que se fija
aca es el real, no el idealizado:

- la primera instancia crea el mutex con nombre y queda como primaria;
- una segunda instancia detecta `ERROR_ALREADY_EXISTS` y no es primaria;
- esa segunda instancia puede senalar el evento para que la primaria muestre su ventana;
- el mutex se libera cuando el proceso primario muere, sea por salida normal o porque otro
  proceso lo mata (Windows cierra los handles), asi que nunca queda un lock huerfano.

Las pruebas de proceso real corren el guard en un interprete hijo con nombres de mutex y
evento unicos por test: el estado de un mutex con nombre es global a la sesion de Windows y
los handles no se pueden cerrar desde la API publica del guard, asi que compartir nombres
entre tests los acoplaria.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

import gestor_luces
from gestor_luces.adapters.system.single_instance import SingleInstanceGuard

#: Techo de espera para cada condicion observable (arranque de un hijo, salida de un hijo).
DEADLINE_SECONDS = 20.0
#: Cadencia del sondeo; el resultado siempre lo decide la condicion, nunca este tiempo.
POLL_SECONDS = 0.01
#: Ventana para que un callback que NO debe dispararse lo haga, si el guard escuchara sin ser
#: primario: tres ciclos del sondeo de 500 ms del listener.
QUIET_WINDOW_SECONDS = 3 * 500 / 1000

_SRC_ROOT = Path(gestor_luces.__file__).resolve().parents[1]

#: Hijo de prueba: adquiere la guarda, publica su veredicto y se queda vivo leyendo stdin
#: hasta `exit` (o hasta EOF, que es el modo sonda: adquiere, informa y sale).
_INSTANCE_SCRIPT = """
import sys
from pathlib import Path

from gestor_luces.adapters.system.single_instance import SingleInstanceGuard

mutex_name, event_name, marker_path = sys.argv[1], sys.argv[2], sys.argv[3]
guard = SingleInstanceGuard(mutex_name=mutex_name, event_name=event_name)
verdict = "primary" if guard.acquire() else "secondary"
Path(marker_path).write_text(verdict, encoding="utf-8")
for line in sys.stdin:
    if line.strip() == "exit":
        break
guard.release()
"""


@dataclass(frozen=True)
class HeldInstance:
    """Proceso primario vivo con su lock tomado, mas el directorio para publicar veredictos."""

    mutex_name: str
    event_name: str
    child: subprocess.Popen[str]
    directory: Path


def _wait_until(predicate: Callable[[], bool], description: str) -> None:
    """Espera acotada a que la condicion se cumpla, sin dormir un tiempo fijo."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"{description} (within {DEADLINE_SECONDS}s)")


def _unique_names() -> tuple[str, str]:
    """Nombres de mutex y evento unicos por test (estado global de la sesion de Windows)."""
    suffix = uuid.uuid4().hex
    return (
        f"Local\\GestorDeLuces.Test.{suffix}",
        f"Local\\GestorDeLuces.Test.Show.{suffix}",
    )


def _run_instance(
    mutex_name: str, event_name: str, marker: Path, *, hold: bool
) -> subprocess.Popen[str]:
    """Lanza un hijo que adquiere la guarda; `hold` lo deja vivo hasta que se le pida salir."""
    # `sys.executable` (el venv del proyecto) mas el codigo fijo de este modulo: ninguna parte
    # de la invocacion es entrada no confiable, y los nombres de mutex son uuid por test.
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _INSTANCE_SCRIPT, mutex_name, event_name, str(marker)],
        stdin=subprocess.PIPE if hold else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(_SRC_ROOT.parent),
        env={**os.environ, "PYTHONPATH": str(_SRC_ROOT)},
    )


def _verdict(marker: Path) -> str:
    """Veredicto publicado por el hijo (`primary` o `secondary`), esperando a que lo escriba."""
    report = ""

    def _published() -> bool:
        nonlocal report
        try:
            report = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        return report in {"primary", "secondary"}

    _wait_until(_published, f"the child instance published no verdict in {marker}")
    return report


def _probe_instance(mutex_name: str, event_name: str, marker: Path) -> str:
    """Arranca un hijo sonda que adquiere la guarda, informa y sale enseguida."""
    child = _run_instance(mutex_name, event_name, marker, hold=False)
    try:
        stdout, stderr = child.communicate(timeout=DEADLINE_SECONDS)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=DEADLINE_SECONDS)
    assert child.returncode == 0, f"probe instance failed: {stderr or stdout}"
    return _verdict(marker)


def _probe(held: HeldInstance, label: str) -> str:
    """Veredicto de otra instancia lanzada mientras (o despues de) la primaria vive."""
    return _probe_instance(held.mutex_name, held.event_name, held.directory / f"{label}.txt")


def _stop_instance(child: subprocess.Popen[str]) -> None:
    """Pide al hijo que salga por la via normal y verifica que haya salido."""
    assert child.stdin is not None
    child.stdin.write("exit\n")
    child.stdin.flush()
    child.stdin.close()
    child.wait(timeout=DEADLINE_SECONDS)


def _kill_instance(child: subprocess.Popen[str]) -> None:
    """Mata el hijo sin darle chance de liberar nada (el caso del proceso colgado)."""
    child.kill()
    child.wait(timeout=DEADLINE_SECONDS)


@pytest.fixture
def held(tmp_path: Path) -> Iterator[HeldInstance]:
    """Hijo primario que retiene el lock, con garantia de que no sobrevive al test."""
    mutex_name, event_name = _unique_names()
    marker = tmp_path / "primary.txt"
    child = _run_instance(mutex_name, event_name, marker, hold=True)
    try:
        assert _verdict(marker) == "primary", "the first instance did not become primary"
        yield HeldInstance(mutex_name, event_name, child, tmp_path)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=DEADLINE_SECONDS)


@pytest.mark.skipif(sys.platform != "win32", reason="the guard is a no-op outside Windows")
def test_a_second_guard_on_the_same_mutex_is_not_primary() -> None:
    """La deteccion es `ERROR_ALREADY_EXISTS`: el segundo create del mutex no es primario."""
    mutex_name, event_name = _unique_names()
    first = SingleInstanceGuard(mutex_name=mutex_name, event_name=event_name)
    second = SingleInstanceGuard(mutex_name=mutex_name, event_name=event_name)

    assert first.acquire() is True
    assert first.is_primary is True
    assert second.acquire() is False
    assert second.is_primary is False


@pytest.mark.skipif(sys.platform != "win32", reason="the guard is a no-op outside Windows")
def test_the_primary_listener_runs_the_callback_when_a_second_launch_signals() -> None:
    """`signal_existing_instance()` despierta al listener de la primaria (mostrar ventana)."""
    mutex_name, event_name = _unique_names()
    primary = SingleInstanceGuard(mutex_name=mutex_name, event_name=event_name)
    secondary = SingleInstanceGuard(mutex_name=mutex_name, event_name=event_name)
    assert primary.acquire() is True
    assert secondary.acquire() is False
    requests: list[str] = []
    requested = threading.Event()

    def _on_show_requested() -> None:
        requests.append("show")
        requested.set()

    try:
        primary.listen(_on_show_requested)
        secondary.signal_existing_instance()
        assert requested.wait(timeout=DEADLINE_SECONDS), (
            "the primary instance never received the show-window request"
        )
        assert requests == ["show"]
    finally:
        primary.release()


@pytest.mark.skipif(sys.platform != "win32", reason="the guard is a no-op outside Windows")
def test_a_non_primary_guard_never_listens_for_a_second_launch() -> None:
    """Solo la primaria escucha: `listen()` en la secundaria no puede mostrar nada."""
    mutex_name, event_name = _unique_names()
    primary = SingleInstanceGuard(mutex_name=mutex_name, event_name=event_name)
    secondary = SingleInstanceGuard(mutex_name=mutex_name, event_name=event_name)
    assert primary.acquire() is True
    assert secondary.acquire() is False
    requests: list[str] = []

    def _on_show_requested() -> None:
        requests.append("show")

    try:
        secondary.listen(_on_show_requested)
        primary.signal_existing_instance()
        quiet_deadline = time.monotonic() + QUIET_WINDOW_SECONDS
        while time.monotonic() < quiet_deadline:
            assert requests == [], "a non-primary guard answered a show-window request"
            time.sleep(POLL_SECONDS)
    finally:
        primary.release()
        secondary.release()
    assert requests == []


@pytest.mark.skipif(sys.platform != "win32", reason="the guard is a no-op outside Windows")
def test_lock_is_released_when_the_primary_process_exits(held: HeldInstance) -> None:
    """Viva la primaria, otra instancia es secundaria; cuando sale, la siguiente es primaria."""
    assert _probe(held, "while-running") == "secondary"

    _stop_instance(held.child)

    assert _probe(held, "after-exit") == "primary"


@pytest.mark.skipif(sys.platform != "win32", reason="the guard is a no-op outside Windows")
def test_lock_does_not_survive_a_killed_primary_process(held: HeldInstance) -> None:
    """Comportamiento real: matar el proceso libera el mutex, no queda un lock huerfano."""
    assert _probe(held, "while-running") == "secondary"

    _kill_instance(held.child)

    assert _probe(held, "after-kill") == "primary"


def test_outside_windows_the_guard_is_a_no_op_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    """En plataformas no-Windows todo lanzamiento es primario y no se abre ningun handle."""
    monkeypatch.setattr(sys, "platform", "linux")
    guard = SingleInstanceGuard()
    requests: list[str] = []

    assert guard.acquire() is True
    assert guard.is_primary is True
    guard.signal_existing_instance()
    guard.listen(lambda: requests.append("show"))
    guard.release()

    assert requests == []
