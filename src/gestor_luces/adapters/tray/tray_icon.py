"""Controlador del icono de bandeja del sistema basado en `pystray`.

Decisiones de hilos (verificadas con pystray 0.19.5 y pywebview 6.2.1 en Windows):
- `webview.start()` debe ser duenio del hilo principal, por eso `Icon.run` se lanza en
  un hilo demonio propio; `run_detached()` se evita porque crea un hilo no demonio que
  mantiene vivo el proceso si alguna ruta de cierre omite `stop()`.
- Win32 invoca los callbacks del menu dentro del bombeo de mensajes del icono. Una
  llamada UDP lenta alli congelaria la bandeja, asi que cada accion se despacha a un
  ejecutor (hilo de trabajo) y el bombeo queda libre de inmediato.
- pystray construye el HMENU nativo solo en `update_menu()`, no al abrirlo; por eso el
  menu se recalcula de forma explicita tras cada cambio de estado.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import threading
from typing import Any, Protocol

from PIL import Image, ImageDraw
import pystray

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

_LOGGER = logging.getLogger(__name__)

ICON_NAME = "gestor_luces"
ICON_SIZE = 64
_SUPERSAMPLE = 4

IconFactory = Callable[[str, Image.Image, str, pystray.Menu], Any]
Executor = Callable[[Callable[[], None]], None]


class TrayActions(Protocol):
    """Subconjunto sincrono y seguro entre hilos del `WebviewBridge` que usa la bandeja."""

    def set_power(self, is_on: bool) -> dict[str, Any]: ...

    def set_brightness(self, brightness: int) -> dict[str, Any]: ...

    def apply_custom_scene(self, scene_id: str) -> dict[str, Any]: ...

    def cancel_sleep_timer(self) -> dict[str, Any]: ...

    def get_tray_snapshot(self) -> dict[str, Any]: ...


def render_icon_image(rgb: tuple[int, int, int], size: int = ICON_SIZE) -> Image.Image:
    """Dibuja un disco RGBA teñido con el color del haz, sin depender de archivos binarios.

    Se dibuja a mayor resolucion y luego se reduce para obtener bordes suavizados, y se
    agrega un contorno oscuro para que el disco se distinga en barras de tareas claras.
    """
    large = size * _SUPERSAMPLE
    image = Image.new("RGBA", (large, large), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset = large // 16
    draw.ellipse(
        (inset, inset, large - inset - 1, large - inset - 1),
        fill=(*rgb, 255),
        outline=(13, 15, 18, 255),
        width=max(1, large // 20),
    )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def _default_icon_factory(
    name: str,
    image: Image.Image,
    title: str,
    menu: pystray.Menu,
) -> pystray.Icon:
    return pystray.Icon(name, image, title, menu)


def _default_executor(task: Callable[[], None]) -> None:
    threading.Thread(target=task, name="GestorLucesTrayAction", daemon=True).start()


def _constant(value: bool) -> Callable[[Any], bool]:
    """Envuelve un booleano porque pystray exige callables para `checked`."""
    return lambda _item: value


class TrayController:
    """Posee el `pystray.Icon`, traduce el modelo de menu y despacha sus acciones."""

    def __init__(
        self,
        actions: TrayActions,
        *,
        show_window: Callable[[], None],
        hide_window: Callable[[], None],
        quit_app: Callable[[], None],
        is_window_visible: Callable[[], bool],
        notify_ui: Callable[[], None] | None = None,
        icon_factory: IconFactory | None = None,
        executor: Executor | None = None,
        poll_interval: float = 5.0,
    ) -> None:
        self._actions = actions
        self._show_window = show_window
        self._hide_window = hide_window
        self._quit_app = quit_app
        self._is_window_visible = is_window_visible
        self._notify_ui = notify_ui
        self._icon_factory = icon_factory or _default_icon_factory
        self._executor = executor or _default_executor
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._refresh_requested = threading.Event()
        self._icon: Any = None
        self._signature: tuple[Any, ...] | None = None
        self._spec: list[TrayMenuEntry] = build_tray_menu_spec(
            is_on=False,
            brightness=100,
            presets=[],
            window_visible=True,
            sleep_timer_active=False,
        )
        self._title = build_tray_title(False, 100)
        self._rgb = resolve_icon_rgb(is_on=False, mode=None, color=None, temperature=None)
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

    def _toggle_window_visibility(self) -> None:
        """Conmuta entre mostrar y ocultar la ventana con base en el estado real."""
        if self._safe_window_visible():
            self._hide_window()
        else:
            self._show_window()

    @property
    def title(self) -> str:
        with self._lock:
            return self._title

    def build_menu(self) -> pystray.Menu:
        """Crea un menu dinamico que lee el modelo cacheado en cada reconstruccion.

        pystray evalua el generador varias veces por apertura; leer la cache evita
        una consulta al bucle asincrono por cada evaluacion.
        """
        return pystray.Menu(self._current_menu_items)

    def start(self) -> None:
        """Crea el icono y lanza su bombeo de mensajes y el refresco en hilos demonio."""
        if self._icon is not None or self._stopped.is_set():
            return
        self.refresh()
        self._icon = self._icon_factory(
            ICON_NAME,
            render_icon_image(self._rgb),
            self._title,
            self.build_menu(),
        )
        threading.Thread(target=self._icon.run, name="GestorLucesTray", daemon=True).start()
        threading.Thread(
            target=self._refresh_worker,
            name="GestorLucesTrayRefresh",
            daemon=True,
        ).start()

    def stop(self) -> None:
        """Retira el icono de la bandeja; seguro de invocar varias veces y desde cualquier hilo."""
        if self._stopped.is_set():
            return
        self._stopped.set()
        self._refresh_requested.set()
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:
            _LOGGER.exception("Failed to stop the tray icon.")

    def request_refresh(self) -> None:
        """Solicita un refresco asincrono sin bloquear al llamador (p. ej. el hilo GUI)."""
        self._refresh_requested.set()

    def refresh(self) -> None:
        """Recalcula menu, tooltip e imagen; solo toca Win32 si algo cambio realmente."""
        try:
            snapshot = self._actions.get_tray_snapshot()
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
        title = build_tray_title(is_on, brightness, language=lang)
        rgb = resolve_icon_rgb(
            is_on=is_on,
            mode=snapshot.get("mode"),
            color=snapshot.get("color"),
            temperature=snapshot.get("temperature"),
        )
        signature = (tuple(spec), title, rgb)
        with self._lock:
            if signature == self._signature:
                return
            self._signature = signature
            self._spec, self._title, self._rgb = spec, title, rgb
        self._apply_to_icon(spec, title, rgb)

    def dispatch(self, action_id: str, payload: Any = None) -> None:
        """Encola una accion del menu en el ejecutor para no bloquear el bombeo Win32."""
        self._executor(lambda: self._run_action(action_id, payload))

    def _run_action(self, action_id: str, payload: Any) -> None:
        handler = self._handlers.get(action_id)
        if handler is None:
            _LOGGER.warning("Unknown tray action: %s", action_id)
            return
        try:
            handler(payload)
        except Exception:
            # Un fallo de red o de ventana nunca debe propagarse al hilo de la bandeja.
            _LOGGER.exception("Tray action '%s' failed.", action_id)
        if action_id != ACTION_QUIT:
            self.refresh()

    def _call_bridge(self, method: Callable[..., dict[str, Any]], *args: Any) -> None:
        """Invoca el puente y sincroniza la ventana aunque la operacion haya fallado."""
        response = method(*args)
        if isinstance(response, dict) and not response.get("ok", True):
            _LOGGER.warning("Tray action rejected by the service: %s", response.get("error"))
        if self._notify_ui is not None:
            try:
                self._notify_ui()
            except Exception:
                _LOGGER.exception("Failed to notify the web UI about a tray change.")

    def _apply_to_icon(
        self,
        spec: list[TrayMenuEntry],
        title: str,
        rgb: tuple[int, int, int],
    ) -> None:
        icon = self._icon
        if icon is None or self._stopped.is_set():
            return
        try:
            with self._lock:
                if (tuple(spec), title, rgb) != self._signature:
                    return
                icon.icon = render_icon_image(rgb)
                icon.title = title
            # Importante: `update_menu()` evalua `_current_menu_items()`, que adquiere
            # `self._lock`. Como `threading.Lock` no es reentrante, debemos llamarlo
            # fuera del bloque `with self._lock:` para no provocar un interbloqueo (deadlock).
            icon.update_menu()
        except Exception:
            _LOGGER.exception("Failed to update the tray icon.")

    def _refresh_worker(self) -> None:
        """Atiende solicitudes de refresco y sondea periodicamente cambios silenciosos.

        El sondeo cubre cambios que no pasan por la UI ni por la bandeja, como el
        apagado automatico del temporizador; gracias a la firma comparada, un sondeo
        sin cambios no reconstruye el menu nativo.
        """
        timeout = self._poll_interval if self._poll_interval > 0 else None
        while not self._stopped.is_set():
            self._refresh_requested.wait(timeout=timeout)
            if self._stopped.is_set():
                break
            self._refresh_requested.clear()
            self.refresh()

    def _safe_window_visible(self) -> bool:
        try:
            return bool(self._is_window_visible())
        except Exception:
            _LOGGER.exception("Failed to read window visibility.")
            return True

    def _current_menu_items(self) -> tuple[pystray.MenuItem, ...]:
        with self._lock:
            entries = list(self._spec)
        return tuple(self._to_menu_item(entry) for entry in entries)

    def _to_menu_item(self, entry: TrayMenuEntry) -> pystray.MenuItem:
        if entry.is_separator:
            return pystray.Menu.SEPARATOR
        if entry.children:
            submenu = pystray.Menu(*(self._to_menu_item(child) for child in entry.children))
            return pystray.MenuItem(entry.label, submenu, enabled=entry.enabled)
        return pystray.MenuItem(
            entry.label,
            self._make_handler(entry) if entry.action_id else None,
            checked=_constant(entry.checked) if entry.checked is not None else None,
            radio=entry.radio,
            default=entry.is_default,
            enabled=entry.enabled,
        )

    def _make_handler(self, entry: TrayMenuEntry) -> Callable[[], None]:
        # Si es el item por defecto (Show/Hide window) y el usuario hace clic izquierdo en el
        # icono antes de que termine un refresh en segundo plano, conmutamos la visibilidad
        # verificando el estado en vivo para que un clic en el icono oculto SIEMPRE abra la ventana.
        action_id = entry.action_id
        payload = entry.payload
        is_window_toggle = action_id in (ACTION_SHOW_WINDOW, ACTION_HIDE_WINDOW)

        def _handler() -> None:
            if is_window_toggle and entry.is_default:
                self.dispatch("toggle_window", None)
            else:
                self.dispatch(action_id, payload)

        return _handler
