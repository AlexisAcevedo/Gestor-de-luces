"""Contrato de ida y vuelta con JavaScript: tabla de despacho explicita y fachada `JsApi`.

pywebview publica todo atributo publico del objeto `js_api`, asi que la superficie de IPC
se declara aqui a mano, en orden alfabetico, para que sea auditable de un vistazo. Antes se
inferia reflejando `dir(WebviewBridge)`, de modo que cualquier metodo publico nuevo quedaba
expuesto a la vista sin que nadie lo decidiera (T-4.2).

Tambien vive aqui el ajuste de altura de la ventana: `JsApi.fit_window_height` lo
reimplementa para no exponer el handle nativo, y `WindowFitHandlers` es el camino de
respaldo del propio puente.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import MethodType
from typing import TYPE_CHECKING, Any

from gestor_luces.adapters.ui_webview.handlers import BridgeHandlers
from gestor_luces.adapters.ui_webview.lifecycle import BridgeLifecycle

if TYPE_CHECKING:
    from gestor_luces.adapters.ui_webview.bridge import WebviewBridge

_LOGGER = logging.getLogger(__name__)

FIT_WINDOW_MIN_PX = 200
FIT_WINDOW_MAX_PX = 4000

JS_API_EXCLUDED: frozenset[str] = frozenset(
    {
        "get_tray_snapshot",
        "set_fit_window_callback",
        "set_state_change_listener",
        "shutdown",
    }
)

# Tabla de despacho explicita: nombre visible desde JavaScript -> metodo del puente.
# Las operaciones programadas, el idioma y el tema los aporta `BridgeLifecycle`; el
# resto, `BridgeHandlers`.
# `fit_window_height` no esta aqui a proposito: `JsApi` lo reimplementa para no exponer el
# handle nativo de la ventana.
JS_API_DISPATCH: dict[str, Callable[..., Any]] = {
    "add_manual_bulb": BridgeHandlers.add_manual_bulb,
    "apply_custom_scene": BridgeHandlers.apply_custom_scene,
    "cancel_sleep_timer": BridgeLifecycle.cancel_sleep_timer,
    "delete_custom_scene": BridgeHandlers.delete_custom_scene,
    "discover_bulbs": BridgeHandlers.discover_bulbs,
    "get_ambilight_status": BridgeHandlers.get_ambilight_status,
    "get_autostart": BridgeHandlers.get_autostart,
    "get_initial_state": BridgeHandlers.get_initial_state,
    "get_music_sync_status": BridgeHandlers.get_music_sync_status,
    "get_sleep_timer_status": BridgeLifecycle.get_sleep_timer_status,
    "refresh_states": BridgeHandlers.refresh_states,
    "rename_bulb": BridgeHandlers.rename_bulb,
    "save_custom_scene": BridgeHandlers.save_custom_scene,
    "select_targets": BridgeHandlers.select_targets,
    "set_autostart": BridgeHandlers.set_autostart,
    "set_brightness": BridgeHandlers.set_brightness,
    "set_builtin_scene": BridgeHandlers.set_builtin_scene,
    "set_color": BridgeHandlers.set_color,
    "set_custom_scene_favorite": BridgeHandlers.set_custom_scene_favorite,
    "set_language": BridgeLifecycle.set_language,
    "set_power": BridgeHandlers.set_power,
    "set_temperature": BridgeHandlers.set_temperature,
    "set_theme": BridgeLifecycle.set_theme,
    "start_ambilight": BridgeHandlers.start_ambilight,
    "start_music_sync": BridgeHandlers.start_music_sync,
    "start_sleep_timer": BridgeLifecycle.start_sleep_timer,
    "stop_ambilight": BridgeHandlers.stop_ambilight,
    "stop_music_sync": BridgeHandlers.stop_music_sync,
    "update_custom_scene": BridgeHandlers.update_custom_scene,
}


def _run_fit_callback(callback: Callable[[int], bool], content_px: int) -> dict[str, Any]:
    """Invoca el callback nativo de ajuste de ventana y sella su resultado para JavaScript.

    Compartido por `JsApi` y `WindowFitHandlers`: es el unico punto de frontera del ajuste,
    asi que no hay dos politicas de error para el mismo callback.
    """
    try:
        return {"ok": bool(callback(content_px))}
    # FRONTERA: el callback es el host nativo de la ventana (pywebview, pythonnet/WinForms y
    # ctypes para DWM), que no garantiza el tipo de excepcion. Su fallo debe volver a la
    # vista como error de ajuste en lugar de propagarse por el puente.
    except Exception as exc:
        _LOGGER.debug("Window fit callback failed.", exc_info=True)
        return {"ok": False, "error": str(exc)}


class WindowFitHandlers:
    """Contrato de ajuste de altura de la ventana hospedada (fuera de la tabla JS)."""

    def set_fit_window_callback(self, callback: Callable[[int], bool] | None) -> None:
        """Registra o reemplaza el callback nativo para auto-ajustar la altura de la ventana."""
        self._fit_window_height = callback

    def fit_window_height(self, content_px: int) -> dict[str, Any]:
        """Solicita al host redimensionar la ventana para que el alto util coincida con
        `content_px`."""
        if isinstance(content_px, bool) or not isinstance(content_px, int):
            return {"ok": False, "error": "content_px must be an integer."}
        if not FIT_WINDOW_MIN_PX <= content_px <= FIT_WINDOW_MAX_PX:
            return {
                "ok": False,
                "error": f"content_px must be between {FIT_WINDOW_MIN_PX} and {FIT_WINDOW_MAX_PX}.",
            }
        callback = getattr(self, "_fit_window_height", None)
        if callback is None:
            return {"ok": False, "error": "Window fit callback is not configured."}
        return _run_fit_callback(callback, content_px)


class JsApi:
    """Fachada que expone a JavaScript unicamente los metodos de `JS_API_DISPATCH`.

    Los metodos de ciclo de vida y de bandeja del puente (`JS_API_EXCLUDED`) quedan fuera
    para que el contenido web no pueda cerrar la app ni manipular la bandeja del sistema.
    """

    def __init__(
        self,
        bridge: WebviewBridge,
        fit_window: Callable[[int], bool] | None = None,
    ) -> None:
        self._bridge = bridge
        self._fit_window = fit_window
        for name, handler in JS_API_DISPATCH.items():
            setattr(self, name, MethodType(handler, bridge))

    def fit_window_height(self, content_px: int) -> dict[str, Any]:
        """Solicita al host redimensionar la ventana sin exponer el handle nativo a JavaScript."""
        if isinstance(content_px, bool) or not isinstance(content_px, int):
            return {"ok": False, "error": "content_px must be an integer."}
        if not FIT_WINDOW_MIN_PX <= content_px <= FIT_WINDOW_MAX_PX:
            return {
                "ok": False,
                "error": f"content_px must be between {FIT_WINDOW_MIN_PX} and {FIT_WINDOW_MAX_PX}.",
            }
        callback = getattr(self, "_fit_window", None)
        if callback is not None:
            return _run_fit_callback(callback, content_px)
        bridge = getattr(self, "_bridge", None)
        if bridge is not None and hasattr(bridge, "fit_window_height"):
            return bridge.fit_window_height(content_px)
        return {"ok": False, "error": "Window fit callback is not configured."}
