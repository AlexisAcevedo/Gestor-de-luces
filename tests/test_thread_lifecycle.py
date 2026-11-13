"""Cierre sin hilos huerfanos: bandeja, bucle del puente, guarda y app de escritorio.

Inventario de nombres verificado contra `threading.Thread(` del codigo y documentado en
`docs/architecture.md` §2:

- `GestorLucesTray`, `GestorLucesTrayRefresh`, `GestorLucesTrayAction` (bandeja).
- `GestorLucesAsyncLoop` (bucle de eventos del puente IPC).
- `GestorLucesMenuSync`, `GestorLucesHideOnClose`, `GestorLucesHideOnMinimize` (escritorio).
- `GestorLucesSingleInstance` (guarda de instancia unica).

Cada espera es acotada y sobre una condicion observable (`threading.enumerate()`, un efecto
del hilo): no hay `sleep` de duracion fija, y el mensaje de fallo nombra la condicion que no
se cumplio. Los dobles no abren ningun toolkit grafico, audio ni red.
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from gestor_luces.adapters.system.single_instance import SingleInstanceGuard
from gestor_luces.adapters.tray.menu_model import ACTION_TURN_OFF
from gestor_luces.adapters.tray.tray_icon import (
    ICON_THREAD_NAME,
    REFRESH_THREAD_NAME,
    TrayController,
)
from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.ui_webview.lifecycle import ASYNC_LOOP_THREAD_NAME
from gestor_luces.desktop import app as desktop_app
from gestor_luces.desktop.app import (
    HIDE_ON_CLOSE_THREAD_NAME,
    HIDE_ON_MINIMIZE_THREAD_NAME,
    MENU_SYNC_THREAD_NAME,
    DesktopApplication,
)

#: Nombre literal del ejecutor de acciones de la bandeja (`tray_icon._default_executor`):
#: no se exporta como constante porque solo el ejecutor por defecto lo usa.
TRAY_ACTION_THREAD_NAME = "GestorLucesTrayAction"
#: Nombre literal del hilo que escucha un segundo lanzamiento (`single_instance.listen`).
SINGLE_INSTANCE_THREAD_NAME = "GestorLucesSingleInstance"

TRAY_THREAD_NAMES = frozenset({ICON_THREAD_NAME, REFRESH_THREAD_NAME, TRAY_ACTION_THREAD_NAME})
#: Todos los nombres de hilo que declara la aplicacion (ver docs/architecture.md §2).
APP_THREAD_NAMES = frozenset(
    {
        ICON_THREAD_NAME,
        REFRESH_THREAD_NAME,
        TRAY_ACTION_THREAD_NAME,
        ASYNC_LOOP_THREAD_NAME,
        MENU_SYNC_THREAD_NAME,
        HIDE_ON_CLOSE_THREAD_NAME,
        HIDE_ON_MINIMIZE_THREAD_NAME,
        SINGLE_INSTANCE_THREAD_NAME,
    }
)
#: Hilos que arranca la aplicacion de escritorio y que no deben sobrevivir al cierre.
DESKTOP_THREAD_NAMES = APP_THREAD_NAMES - {SINGLE_INSTANCE_THREAD_NAME}

DEADLINE_SECONDS = 10.0
POLL_SECONDS = 0.01


def _live_thread_names() -> set[str]:
    """Nombres de los hilos vivos en este instante (incluye hilos nativos registrados)."""
    return {thread.name for thread in threading.enumerate()}


def _thread_named(name: str) -> threading.Thread:
    """Devuelve el hilo vivo con ese nombre; falla si no existe."""
    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    raise AssertionError(f"no live thread named {name!r}: {sorted(_live_thread_names())}")


def _wait_until(predicate: Callable[[], bool], description: str) -> None:
    """Espera acotada a que la condicion se cumpla, sondeando sin dormir un tiempo fijo."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"{description} (within {DEADLINE_SECONDS}s)")


class _FakeTrayActions:
    """Acciones sincronas de la bandeja; registra el hilo que ejecuta cada llamada."""

    def __init__(self) -> None:
        self.threads: list[threading.Thread] = []

    def set_power(self, is_on: bool) -> dict[str, Any]:
        self.threads.append(threading.current_thread())
        return {"ok": True}

    def set_brightness(self, brightness: int) -> dict[str, Any]:
        self.threads.append(threading.current_thread())
        return {"ok": True}

    def apply_custom_scene(self, scene_id: str) -> dict[str, Any]:
        self.threads.append(threading.current_thread())
        return {"ok": True}

    def cancel_sleep_timer(self) -> dict[str, Any]:
        self.threads.append(threading.current_thread())
        return {"ok": True}

    def get_tray_snapshot(self) -> dict[str, Any]:
        return {
            "is_on": False,
            "brightness": 50,
            "presets": [],
            "language": "en",
            "theme": "architectural-stone",
        }


class _BlockingTrayView:
    """Vista de bandeja que bloquea `run` como un bombeo nativo, sin abrir un toolkit."""

    def __init__(self) -> None:
        self.run_threads: list[threading.Thread] = []
        self.apply_threads: list[threading.Thread] = []
        self.applies: list[str] = []
        self._stop = threading.Event()

    def run(self) -> None:
        self.run_threads.append(threading.current_thread())
        self._stop.wait(timeout=DEADLINE_SECONDS)

    def stop(self) -> None:
        self._stop.set()

    def apply(
        self,
        spec: list[Any],
        title: str,
        rgb: tuple[int, int, int],
        theme: str,
    ) -> None:
        self.apply_threads.append(threading.current_thread())
        self.applies.append(title)


def test_stopping_the_tray_controller_leaves_no_tray_threads() -> None:
    """`stop()` retira la vista y deja que sus tres hilos terminen; ninguno queda vivo."""
    # Lo que ya estaba vivo al empezar no es responsabilidad de esta prueba.
    preexisting = APP_THREAD_NAMES & _live_thread_names()
    view = _BlockingTrayView()
    actions = _FakeTrayActions()
    tray = TrayController(
        actions,
        show_window=lambda: None,
        hide_window=lambda: None,
        quit_app=lambda: None,
        is_window_visible=lambda: True,
        view_factory=lambda _dispatch: view,
    )
    try:
        tray.start()
        _wait_until(
            lambda: {ICON_THREAD_NAME, REFRESH_THREAD_NAME} <= _live_thread_names(),
            "the tray view and refresh threads never started",
        )

        # Una accion del menu corre en un hilo de trabajo de vida corta, no en el bombeo.
        tray.dispatch(ACTION_TURN_OFF)
        _wait_until(
            lambda: bool(actions.threads),
            "the tray action never reached the bridge",
        )
        _wait_until(
            lambda: TRAY_ACTION_THREAD_NAME not in _live_thread_names(),
            "the short-lived tray action thread never finished",
        )
        # Solo el hilo de refresco aplica estado nativo (regla de T-3.6).
        _wait_until(
            lambda: any(t.name == REFRESH_THREAD_NAME for t in view.apply_threads),
            "the refresh thread never applied the tray state",
        )
    finally:
        tray.stop()

    _wait_until(
        lambda: not (TRAY_THREAD_NAMES & _live_thread_names()),
        f"tray.stop() left threads alive: {sorted(TRAY_THREAD_NAMES & _live_thread_names())}",
    )
    leaked = (APP_THREAD_NAMES & _live_thread_names()) - preexisting
    assert leaked == set(), f"threads with an app name left alive: {sorted(leaked)}"

    captured = [*view.run_threads, *view.apply_threads, *actions.threads]
    app_named = [thread for thread in captured if thread.name in TRAY_THREAD_NAMES]
    # Los tres nombres existen de verdad (el test no pasa por no haber hilos que mirar)...
    assert {thread.name for thread in app_named} == set(TRAY_THREAD_NAMES)
    # ...y todos son demonio, para que un `stop()` omitido no mantenga vivo el proceso.
    assert all(thread.daemon for thread in app_named)


class _FakeLightControlService:
    """Puerto minimo que consume el puente: sin red, sin audio y sin disco."""

    def __init__(self) -> None:
        self.closed_audio = False

    def get_target_ips(self) -> list[str]:
        return []

    def get_bulb(self, ip: str) -> None:
        return None

    def list_custom_scenes(self) -> list[Any]:
        return []

    def get_sleep_timer_status(self) -> dict[str, Any]:
        return {"active": False}

    def get_language(self) -> str:
        return "en"

    def get_theme(self) -> str:
        return "architectural-stone"

    def stop_ambilight(self) -> None:
        return None

    def stop_music_sync(self, close_sampler: bool = False) -> None:
        return None

    def cancel_sleep_timer(self) -> None:
        return None

    def close_audio_sampler(self) -> None:
        self.closed_audio = True


def test_closing_the_bridge_leaves_no_async_loop_thread() -> None:
    """`shutdown()` detiene y une el hilo del bucle de eventos del puente."""
    bridge = WebviewBridge(service=_FakeLightControlService())
    _wait_until(
        lambda: ASYNC_LOOP_THREAD_NAME in _live_thread_names(),
        "the bridge async loop thread never started",
    )
    loop_thread = _thread_named(ASYNC_LOOP_THREAD_NAME)
    assert loop_thread.daemon is True

    bridge.shutdown()

    _wait_until(
        lambda: ASYNC_LOOP_THREAD_NAME not in _live_thread_names(),
        "shutdown() left the async loop thread alive",
    )
    assert loop_thread.is_alive() is False


class _FakeEvent:
    """Evento de pywebview: solo necesita aceptar `events.<evento> += handler`."""

    def __init__(self) -> None:
        self.handlers: list[Callable[..., Any]] = []

    def __iadd__(self, handler: Callable[..., Any]) -> _FakeEvent:
        self.handlers.append(handler)
        return self

    def fire(self, *args: Any) -> list[Any]:
        return [handler(*args) for handler in self.handlers]


class _FakeWindowEvents:
    """Los cuatro eventos del ciclo de vida que cablea la aplicacion de escritorio."""

    def __init__(self) -> None:
        self.shown = _FakeEvent()
        self.closing = _FakeEvent()
        self.minimized = _FakeEvent()
        self.closed = _FakeEvent()


class _FakeWindow:
    """Ventana nativa sin HWND: registra el hilo que ejecuta cada efecto observable."""

    def __init__(self, on_destroy: Callable[[], None]) -> None:
        self.events = _FakeWindowEvents()
        self.show_threads: list[threading.Thread] = []
        self.hide_threads: list[threading.Thread] = []
        self.destroy_threads: list[threading.Thread] = []
        self.scripts: list[str] = []
        self._on_destroy = on_destroy

    def show(self) -> None:
        self.show_threads.append(threading.current_thread())

    def hide(self) -> None:
        self.hide_threads.append(threading.current_thread())

    def restore(self) -> None:
        return None

    def evaluate_js(self, script: str) -> None:
        self.scripts.append(script)

    def destroy(self) -> None:
        self.destroy_threads.append(threading.current_thread())
        self._on_destroy()


class _FakeWebview:
    """Modulo `webview` falso: crea la ventana y bloquea `start` hasta el cierre."""

    def __init__(self) -> None:
        self.window: _FakeWindow | None = None
        self.closed = threading.Event()
        self.start_kwargs: dict[str, Any] = {}

    def create_window(self, **kwargs: Any) -> _FakeWindow:
        self.window = _FakeWindow(self.closed.set)
        return self.window

    def start(self, **kwargs: Any) -> None:
        self.start_kwargs = kwargs
        self.closed.wait(timeout=DEADLINE_SECONDS)


def test_closing_the_desktop_application_leaves_no_app_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El ciclo real de cierre (Quit, ventana destruida, `cleanup`) no deja hilos vivos."""
    # pywebview crea el perfil WebView2 fuera del repo: en la prueba va al tmp de pytest.
    monkeypatch.setattr(desktop_app, "resolve_default_data_dir", lambda: tmp_path)
    view = _BlockingTrayView()
    monkeypatch.setattr(desktop_app, "create_tray_view", lambda _dispatch: view)

    webview = _FakeWebview()
    service = _FakeLightControlService()
    bridge = WebviewBridge(service=service)
    app = DesktopApplication(
        service=service,
        bridge=bridge,
        index_path=tmp_path / "index.html",
        icon_path=tmp_path / "app.ico",
        ui_dir=tmp_path,
        webview_module=webview,
    )
    app.create_window()
    window = webview.window
    assert window is not None

    # `webview.start()` bloquea el hilo llamador hasta que la ventana se destruye.
    starter = threading.Thread(target=app.start, name="TestDesktopStart", daemon=True)
    starter.start()
    try:
        _wait_until(
            lambda: (
                {
                    MENU_SYNC_THREAD_NAME,
                    ICON_THREAD_NAME,
                    REFRESH_THREAD_NAME,
                    ASYNC_LOOP_THREAD_NAME,
                }
                <= _live_thread_names()
            ),
            "the desktop application never started all of its threads",
        )
        started = {
            name: _thread_named(name)
            for name in (
                MENU_SYNC_THREAD_NAME,
                ICON_THREAD_NAME,
                REFRESH_THREAD_NAME,
                ASYNC_LOOP_THREAD_NAME,
            )
        }
        assert all(thread.daemon for thread in started.values())

        # Hilos cortos: cerrar y minimizar ocultan la ventana desde un hilo propio porque
        # el evento nativo corre en el hilo GUI con `should_lock`.
        assert app.on_closing() is False
        _wait_until(
            lambda: HIDE_ON_CLOSE_THREAD_NAME in {t.name for t in window.hide_threads},
            "the hide-on-close thread never hid the window",
        )
        # Ocultar la ventana pide un refresco: lo aplica el hilo de refresco, fuera del
        # bombeo nativo. Sin esta espera el test dependeria de que llegue antes del cierre.
        _wait_until(
            lambda: REFRESH_THREAD_NAME in {t.name for t in view.apply_threads},
            "the tray refresh thread never applied the state",
        )

        app.show_window()
        app.on_minimized()
        _wait_until(
            lambda: HIDE_ON_MINIMIZE_THREAD_NAME in {t.name for t in window.hide_threads},
            "the hide-on-minimize thread never hid the window",
        )
        _wait_until(
            lambda: (
                not (
                    {HIDE_ON_CLOSE_THREAD_NAME, HIDE_ON_MINIMIZE_THREAD_NAME} & _live_thread_names()
                )
            ),
            "the short-lived hide threads never finished",
        )
    finally:
        app.quit_app()
        starter.join(timeout=DEADLINE_SECONDS)

    assert starter.is_alive() is False, "closing the app did not unblock webview.start()"
    assert window.destroy_threads, "the window was never destroyed on quit"

    # Hilos de la bandeja: mismo contrato de nombre y demonio que en el test anterior.
    tray_named = [
        thread
        for thread in [*view.run_threads, *view.apply_threads]
        if thread.name in {ICON_THREAD_NAME, REFRESH_THREAD_NAME}
    ]
    assert {thread.name for thread in tray_named} == {ICON_THREAD_NAME, REFRESH_THREAD_NAME}
    assert all(thread.daemon for thread in tray_named)

    # `GestorLucesMenuSync` se aparca en `_menu_sync_requested`: `cleanup()` lo marca como
    # cierre y lo despierta, y el bucle comprueba `is_quitting` antes de reaplicar el menu.
    assert started[MENU_SYNC_THREAD_NAME].daemon is True

    _wait_until(
        lambda: not (DESKTOP_THREAD_NAMES & _live_thread_names()),
        "closing the app left threads alive: "
        f"{sorted(DESKTOP_THREAD_NAMES & _live_thread_names())}",
    )


@pytest.mark.skipif(sys.platform != "win32", reason="the listener thread only runs on Windows")
def test_releasing_the_single_instance_guard_stops_its_listener_thread() -> None:
    """`release()` detiene el hilo que espera un segundo lanzamiento (sondeo de 500 ms)."""
    suffix = uuid.uuid4().hex
    guard = SingleInstanceGuard(
        mutex_name=f"Local\\GestorDeLuces.Test.{suffix}",
        event_name=f"Local\\GestorDeLuces.Test.Show.{suffix}",
    )
    assert guard.acquire() is True
    try:
        guard.listen(lambda: None)
        _wait_until(
            lambda: SINGLE_INSTANCE_THREAD_NAME in _live_thread_names(),
            "the single-instance listener thread never started",
        )
        listener = _thread_named(SINGLE_INSTANCE_THREAD_NAME)
        assert listener.daemon is True
    finally:
        guard.release()

    _wait_until(
        lambda: SINGLE_INSTANCE_THREAD_NAME not in _live_thread_names(),
        "release() left the single-instance listener thread alive",
    )
