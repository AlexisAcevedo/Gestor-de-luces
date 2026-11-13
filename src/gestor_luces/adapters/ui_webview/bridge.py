"""Puente IPC entre la ventana de PyWebView (JavaScript) y el puerto de control de luces.

`WebviewBridge` compone las piezas de este paquete: el ciclo de vida asincrono
(`lifecycle`), los casos de uso por capacidad (`handlers`) y el contrato con la vista
(`dispatch`, con la tabla de despacho y la fachada `JsApi`). Este modulo conserva el punto
de importacion historico (`adapters.ui_webview.bridge`) y reexporta todo lo que se
importaba desde el antiguo modulo unico.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gestor_luces.adapters.ui_webview.dispatch import (
    FIT_WINDOW_MAX_PX,
    FIT_WINDOW_MIN_PX,
    JS_API_DISPATCH,
    JS_API_EXCLUDED,
    JsApi,
    WindowFitHandlers,
)
from gestor_luces.adapters.ui_webview.handlers import BridgeHandlers
from gestor_luces.adapters.ui_webview.lifecycle import _SERVICE_CALL_ERRORS, BridgeLifecycle
from gestor_luces.domain.models import Bulb
from gestor_luces.ports.autostart import AutostartManager
from gestor_luces.ports.light_control import LightControlServicePort

__all__ = [
    "FIT_WINDOW_MAX_PX",
    "FIT_WINDOW_MIN_PX",
    "JS_API_DISPATCH",
    "JS_API_EXCLUDED",
    "JsApi",
    "WebviewBridge",
    "WindowFitHandlers",
    "_SERVICE_CALL_ERRORS",
]


class WebviewBridge(BridgeHandlers, BridgeLifecycle, WindowFitHandlers):
    """Adaptador primario que expone los casos de uso de iluminacion a la UI HTML/JS."""

    def __init__(
        self,
        service: LightControlServicePort,
        default_timeout: float = 12.0,
        on_state_changed: Callable[[], None] | None = None,
        autostart: AutostartManager | None = None,
        fit_window_height: Callable[[int], bool] | None = None,
    ) -> None:
        # Frontera hexagonal (T-4.3): el adaptador solo conoce el puerto; la fachada concreta
        # de `gestor_luces.application` se inyecta desde la raiz de composicion.
        self._service = service
        # Private on purpose (see `_on_state_changed`): never exposed to JavaScript.
        self._autostart = autostart
        self._fit_window_height = fit_window_height
        self._default_timeout = default_timeout
        # Atributo privado a proposito: PyWebView expone a JavaScript todo atributo publico
        # del objeto `js_api`, y un callback interno no debe ser invocable desde la vista.
        self._on_state_changed = on_state_changed
        self._monitors_cache: list[dict[str, Any]] | None = None
        self._audio_devices_cache: list[dict[str, Any]] | None = None
        self._start_async_loop()

    def get_tray_snapshot(self) -> dict[str, Any]:
        """Devuelve una vista resumida y serializable del estado para la bandeja del sistema.

        Se construye dentro del bucle asincrono porque los diccionarios del servicio se
        mutan en ese hilo; leerlos desde el hilo de la bandeja podria observar estados
        intermedios o fallar por modificacion concurrente durante la iteracion.
        """

        async def _collect() -> dict[str, Any]:
            return self._collect_tray_snapshot()

        return self._run_async(_collect(), timeout=3.0)

    def _collect_tray_snapshot(self) -> dict[str, Any]:
        """Resume el estado de los focos objetivo, los presets y el temporizador."""
        targets: list[Bulb] = [
            bulb
            for ip in self._service.get_target_ips()
            if (bulb := self._service.get_bulb(ip)) is not None
        ]
        lit = [bulb for bulb in targets if bulb.is_online and bulb.state.is_on]
        reference = lit[0] if lit else (targets[0] if targets else None)
        state = reference.state if reference is not None else None
        color = state.color if state is not None else None
        return {
            "is_on": bool(lit),
            "brightness": state.brightness if state is not None else 100,
            "mode": state.mode.value if state is not None else None,
            "color": [color.r, color.g, color.b] if color is not None else None,
            "temperature": state.temperature if state is not None else None,
            "presets": [
                {"id": scene.id, "name": scene.name, "is_favorite": scene.is_favorite}
                for scene in self._service.list_custom_scenes()
            ],
            "sleep_timer_active": bool(self._service.get_sleep_timer_status().get("active")),
            "language": self._service.get_language(),
            "theme": self._service.get_theme(),
        }
