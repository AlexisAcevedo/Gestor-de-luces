"""Controlador de la bandeja del sistema: modelo de menu, handlers y despacho.

Este modulo no importa ningun toolkit grafico. La vista nativa queda detras del contrato
`TrayView` (`winforms_tray` es la vista principal y `pystray_tray` el respaldo), asi que el
menu nativo puede cambiar de toolkit sin tocar el modelo, los handlers ni el ejecutor.

Decisiones de hilos (verificadas con pywebview 6.2.1 y pythonnet en Windows):
- `webview.start()` debe ser dueño del hilo principal, por eso `TrayView.run` se lanza en
  un hilo demonio propio; nunca en el hilo de la UI ni con un hilo no demonio que pueda
  mantener vivo el proceso si alguna ruta de cierre omite `stop()`.
- Tanto Win32 como WinForms invocan los callbacks del menu dentro del bombeo de mensajes
  de la vista. Una llamada UDP lenta alli congelaria la bandeja, asi que cada accion se
  despacha a un ejecutor (hilo de trabajo) y el bombeo queda libre de inmediato.
- Solo el hilo de refresco aplica estado nativo: una accion del menu nunca reconstruye el
  menu, porque hacerlo mientras el popup esta desplegado invalida sus items (T-3.6).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol

from gestor_luces.adapters.tray.menu_model import (
    ACTION_APPLY_PRESET,
    ACTION_CANCEL_SLEEP_TIMER,
    ACTION_HIDE_WINDOW,
    ACTION_QUIT,
    ACTION_SET_BRIGHTNESS,
    ACTION_SHOW_WINDOW,
    ACTION_TURN_OFF,
    ACTION_TURN_ON,
    TrayMenuEntry,
    TrayPreset,
    build_tray_menu_spec,
    build_tray_title,
    resolve_icon_rgb,
)
from gestor_luces.adapters.tray.tray_view import (
    ICON_NAME,
    ICON_SIZE,
    Dispatch,
    TrayView,
    render_icon_image,
)
from gestor_luces.domain.value_objects import DEFAULT_THEME

_LOGGER = logging.getLogger(__name__)

ICON_THREAD_NAME = "GestorLucesTray"
REFRESH_THREAD_NAME = "GestorLucesTrayRefresh"

Executor = Callable[[Callable[[], None]], None]
ViewFactory = Callable[[Dispatch], TrayView | None]
#: Constructor de icono de la vista de respaldo (`pystray.Icon` en produccion).

#: Fallos reales de un callback de visibilidad: el composition root lee un booleano, asi que
#: solo un callback ajeno puede fallar al leerlo.
_VISIBILITY_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    RuntimeError,
    TypeError,
    AttributeError,
)

__all__ = [
    "ICON_NAME",
    "ICON_SIZE",
    "ICON_THREAD_NAME",
    "REFRESH_THREAD_NAME",
    "TrayActions",
    "TrayController",
    "render_icon_image",
]


class TrayActions(Protocol):
    """Subconjunto sincrono y seguro entre hilos del `WebviewBridge` que usa la bandeja."""

    def set_power(self, is_on: bool) -> dict[str, Any]: ...

    def set_brightness(self, brightness: int) -> dict[str, Any]: ...

    def apply_custom_scene(self, scene_id: str) -> dict[str, Any]: ...

    def cancel_sleep_timer(self) -> dict[str, Any]: ...

    def get_tray_snapshot(self) -> dict[str, Any]: ...


def _default_executor(task: Callable[[], None]) -> None:
    threading.Thread(target=task, name="GestorLucesTrayAction", daemon=True).start()


def _default_view_factory(dispatch: Dispatch) -> TrayView | None:
    """Vista de respaldo: `pystray`. El composition root elige WinForms primero."""
    from gestor_luces.adapters.tray.pystray_tray import create_pystray_view

    return create_pystray_view(dispatch)


class TrayController:
    """Posee el modelo de menu de la bandeja y despacha sus acciones a una vista."""

    def __init__(
        self,
        actions: TrayActions,
        *,
        show_window: Callable[[], None],
        hide_window: Callable[[], None],
        quit_app: Callable[[], None],
        is_window_visible: Callable[[], bool],
        notify_ui: Callable[[], None] | None = None,
        view: TrayView | None = None,
        view_factory: ViewFactory | None = None,
        executor: Executor | None = None,
        poll_interval: float = 5.0,
    ) -> None:
        self._actions = actions
        self._show_window = show_window
        self._hide_window = hide_window
        self._quit_app = quit_app
        self._is_window_visible = is_window_visible
        self._notify_ui = notify_ui
        self._view = view
        self._view_factory: ViewFactory = view_factory or _default_view_factory
        self._executor = executor or _default_executor
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._refresh_requested = threading.Event()
        self._spec: list[TrayMenuEntry] = build_tray_menu_spec(
            is_on=False,
            brightness=100,
            presets=[],
            window_visible=True,
            sleep_timer_active=False,
        )
        self._title = build_tray_title(False, 100)
        self._rgb = resolve_icon_rgb(is_on=False, mode=None, color=None, temperature=None)
        self._theme = DEFAULT_THEME
        self._handlers: dict[str, Callable[[Any], None]] = {
            ACTION_SHOW_WINDOW: lambda _payload: self._show_window(),
            ACTION_HIDE_WINDOW: lambda _payload: self._hide_window(),
            "toggle_window": lambda _payload: self._toggle_window_visibility(),
            ACTION_TURN_ON: lambda _payload: self._call_bridge(self._actions.set_power, True),
            ACTION_TURN_OFF: lambda _payload: self._call_bridge(self._actions.set_power, False),
            ACTION_SET_BRIGHTNESS: lambda payload: self._call_bridge(
                self._actions.set_brightness, int(payload)
            ),
            ACTION_APPLY_PRESET: lambda payload: self._call_bridge(
                self._actions.apply_custom_scene, str(payload)
            ),
            ACTION_CANCEL_SLEEP_TIMER: lambda _payload: self._call_bridge(
                self._actions.cancel_sleep_timer
            ),
            ACTION_QUIT: lambda _payload: self._quit_app(),
        }

    @property
    def spec(self) -> list[TrayMenuEntry]:
        """Ultimo modelo de menu calculado, expuesto para diagnostico y pruebas."""
        with self._lock:
            return list(self._spec)

    @property
    def title(self) -> str:
        """Ultimo tooltip calculado para el icono."""
        with self._lock:
            return self._title

    @property
    def theme(self) -> str:
        """Ultimo tema aplicado a la vista, expuesto para diagnostico y pruebas."""
        with self._lock:
            return self._theme

    @property
    def view(self) -> TrayView | None:
        """Vista nativa en uso (None antes de `start`)."""
        return self._view

    def start(self) -> None:
        """Crea la vista y lanza su bombeo de mensajes y el refresco en hilos demonio."""
        if self._view is not None or self._stopped.is_set():
            return
        view = self._view_factory(self.dispatch)
        if view is None:
            _LOGGER.warning("No tray view is available; the tray icon stays hidden.")
            return
        self._view = view
        # El refresco trae el estado real al icono antes de que arranque el bombeo; el
        # `_push_state` posterior es el respaldo cuando el snapshot falla y la vista no
        # recibio nada (la vista descarta un estado identico al vigente).
        self.refresh()
        self._push_state()
        threading.Thread(target=view.run, name=ICON_THREAD_NAME, daemon=True).start()
        threading.Thread(target=self._refresh_worker, name=REFRESH_THREAD_NAME, daemon=True).start()

    def stop(self) -> None:
        """Retira el icono de la bandeja; seguro de invocar varias veces y desde cualquier hilo."""
        if self._stopped.is_set():
            return
        self._stopped.set()
        self._refresh_requested.set()
        view = self._view
        if view is None:
            return
        self._call_view(view.stop, "Failed to stop the tray view.")

    def _call_view(self, call: Callable[[], None], failure: str) -> None:
        """Ejecuta una llamada a la vista nativa sin propagar su excepcion al controlador.

        FRONTERA (contrato `TrayView`): este modulo no importa ningun toolkit grafico, asi
        que no puede nombrar la excepcion de `pystray` (`ctypes`) ni la del CLR cuando la
        vista es WinForms. Un fallo al detener la vista o al aplicarle estado no puede
        tumbar el hilo de refresco ni el cierre de la app; se registra con traza. Es el
        unico guardia de esta preocupacion: lo comparten `stop` y `_push_state`.
        """
        try:
            call()
        except Exception:
            _LOGGER.exception(failure)

    def request_refresh(self) -> None:
        """Solicita un refresco asincrono sin bloquear al llamador (p. ej. el hilo GUI)."""
        self._refresh_requested.set()

    def refresh(self) -> None:
        """Recalcula menu, tooltip e imagen y entrega el estado a la vista."""
        try:
            snapshot = self._actions.get_tray_snapshot()
        # FRONTERA (refresco de la bandeja): `refresh` es el cuerpo del hilo de refresco y
        # ademas se llama al arrancar, asi que su fallo deja la bandeja congelada o impide
        # que exista. `get_tray_snapshot` corre dentro del bucle del puente (timeout propio)
        # y lee un estado que otro hilo muta: se registra la traza y se conserva el estado
        # anterior, que el sondeo vuelve a intentar en el proximo ciclo.
        except Exception:
            _LOGGER.exception("Failed to read lighting state for the tray.")
            return
        is_on = bool(snapshot.get("is_on"))
        brightness = int(snapshot.get("brightness") or 100)
        lang = str(snapshot.get("language") or "en")
        presets = [
            TrayPreset(
                id=str(raw.get("id")),
                name=str(raw.get("name")),
                is_favorite=bool(raw.get("is_favorite")),
            )
            for raw in snapshot.get("presets") or []
        ]
        spec = build_tray_menu_spec(
            is_on=is_on,
            brightness=brightness,
            presets=presets,
            window_visible=self._safe_window_visible(),
            sleep_timer_active=bool(snapshot.get("sleep_timer_active")),
            language=lang,
        )
        with self._lock:
            self._spec = spec
            self._title = build_tray_title(is_on, brightness, language=lang)
            self._rgb = resolve_icon_rgb(
                is_on=is_on,
                mode=snapshot.get("mode"),
                color=snapshot.get("color"),
                temperature=snapshot.get("temperature"),
            )
            self._theme = str(snapshot.get("theme") or DEFAULT_THEME)
        self._push_state()

    def _push_state(self) -> None:
        """Entrega a la vista el estado cacheado; la vista descarta lo que no cambio."""
        with self._lock:
            spec, title, rgb, theme = self._spec, self._title, self._rgb, self._theme
        view = self._view
        if view is None or self._stopped.is_set():
            return
        self._call_view(
            lambda: view.apply(list(spec), title, rgb, theme),
            "Failed to apply the tray state to the view.",
        )

    def dispatch(self, action_id: str, payload: Any = None) -> None:
        """Encola una accion del menu en el ejecutor para no bloquear el bombeo nativo."""
        # Deja rastro en el log: distinguir "la accion se ejecuto" de "el popup cancelo"
        # es lo unico que permite diagnosticar un menu nativo que no responde.
        _LOGGER.info("Tray action requested: %s", action_id)
        self._executor(lambda: self._run_action(action_id, payload))

    def _run_action(self, action_id: str, payload: Any) -> None:
        handler = self._handlers.get(action_id)
        if handler is None:
            _LOGGER.warning("Unknown tray action: %s", action_id)
            return
        try:
            handler(payload)
        # FRONTERA (hilo de acciones): el ejecutor crea un hilo por accion y el log es el
        # unico lugar donde ver el fallo. Los manejadores cruz a pywebview (mostrar,
        # ocultar, destruir la ventana) y a pythonnet, que no garantizan el tipo de
        # excepcion del host; un fallo de red o de ventana nunca debe propagarse al hilo de
        # la bandeja ni dejar el icono sin su proximo refresco.
        except Exception:
            _LOGGER.exception("Tray action '%s' failed.", action_id)
        if action_id != ACTION_QUIT:
            # Nunca se refresca desde el hilo de la accion: el estado nativo lo aplica el
            # hilo de refresco, que sabe si hay un menu desplegado.
            self.request_refresh()

    def _call_bridge(self, method: Callable[..., dict[str, Any]], *args: Any) -> None:
        """Invoca el puente y sincroniza la ventana aunque la operacion haya fallado."""
        response = method(*args)
        if isinstance(response, dict) and not response.get("ok", True):
            _LOGGER.warning("Tray action rejected by the service: %s", response.get("error"))
        if self._notify_ui is not None:
            # Sin guardia propio: un fallo del aviso a la UI sube a `_run_action`, que ya
            # registra la accion concreta y conserva el refresco posterior.
            self._notify_ui()

    def _refresh_worker(self) -> None:
        """Atiende solicitudes de refresco y sondea periodicamente cambios silenciosos.

        El sondeo cubre cambios que no pasan por la UI ni por la bandeja, como el apagado
        automatico del temporizador; la vista descarta un estado identico al vigente, pero
        el sondeo tambien es lo que reintenta un rebuild que quedo pendiente.
        """
        timeout = self._poll_interval if self._poll_interval > 0 else None
        while not self._stopped.is_set():
            self._refresh_requested.wait(timeout=timeout)
            if self._stopped.is_set():
                break
            self._refresh_requested.clear()
            self.refresh()

    def _toggle_window_visibility(self) -> None:
        """Conmuta entre mostrar y ocultar la ventana con base en el estado real."""
        if self._safe_window_visible():
            self._hide_window()
        else:
            self._show_window()

    def _safe_window_visible(self) -> bool:
        try:
            return bool(self._is_window_visible())
        # Un callback de visibilidad que no responde no puede cortar el refresco (la vista
        # asume ventana visible, que es el estado con el que arranca la app).
        except _VISIBILITY_ERRORS:
            _LOGGER.exception("Failed to read window visibility.")
            return True
