"""Vista de bandeja nativa de WinForms: compone host, icono, menu y acabado.

Motivo (T-3.8): el menu clasico de `pystray` se pinta con el fondo blanco de su clase de
ventana y el texto del tema oscuro queda ilegible; un `ContextMenuStrip` no depende de esa
clase: colores explicitos, submenus que se despliegan al pasar el cursor (`DropDownItems`,
sin hacks de clic) y ningun `HMENU` destruido mientras el menu esta abierto.

Aqui vive la orquestacion: tooltip y tinte se aplican siempre, y solo la reconstruccion del
`ContextMenuStrip` se difiere con el menu desplegado (T-3.6). Las piezas estan en
`winforms_host` (STA), `winforms_icon` (`NotifyIcon` y `HICON`), `winforms_menu` (menu y
submenus) y `winforms_paint` (paleta y dibujo); los simbolos antes importables desde este
modulo se reexportan.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable, Sequence
from typing import Any

from gestor_luces.adapters.tray.menu_model import TrayMenuEntry
from gestor_luces.adapters.tray.tray_view import Dispatch, TrayView, log_applied_menu
from gestor_luces.adapters.tray.winforms_host import (
    _co_initialize_apartment,
    _load_winforms,
    _WinFormsApi,
    clr_errors,
    create_host_form,
    create_view,
    dispose_host,
    invoke_on_ui_thread,
    run_message_loop,
)
from gestor_luces.adapters.tray.winforms_icon import (
    IconCache,
    apply_notify_state,
    create_notify_icon,
    dispose_notify,
)
from gestor_luces.adapters.tray.winforms_menu import (
    MenuSignature,
    StateSignature,
    _build_menu_items,
    _dispose_menu,
    apply_menu_chrome,
    build_context_menu,
    default_entry_target,
    menu_signature,
    state_signature,
)
from gestor_luces.adapters.tray.winforms_paint import (
    DARK_PALETTE,
    DEFAULT_PALETTE,
    LIGHT_PALETTE,
    MENU_ITEM_PADDING_VERTICAL,
    THEME_PALETTES,
    TrayPalette,
    item_paint_style,
    menu_region_geometry,
    paint_menu_item,
    paint_menu_separator,
    parse_hex_color,
    resolve_palette,
    separator_paint_style,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "DARK_PALETTE",
    "DEFAULT_PALETTE",
    "LIGHT_PALETTE",
    "MENU_ITEM_PADDING_VERTICAL",
    "THEME_PALETTES",
    "WinFormsTrayView",
    "_build_menu_items",
    "_load_winforms",
    "create_winforms_view",
    "item_paint_style",
    "menu_region_geometry",
    "menu_signature",
    "paint_menu_item",
    "paint_menu_separator",
    "parse_hex_color",
    "resolve_palette",
    "separator_paint_style",
    "state_signature",
]

#: Estado deseado: modelo de menu, tooltip, color del icono y tema activo.
State = tuple[list[TrayMenuEntry], str, tuple[int, int, int], str]


def create_winforms_view(
    dispatch: Dispatch,
    *,
    destroy_icon: Callable[[int], None] | None = None,
    api: _WinFormsApi | None = None,
    dwmapi: Any = None,
    platform: str | None = None,
) -> TrayView | None:
    """Crea la vista WinForms, o `None` si pythonnet/WinForms no estan disponibles."""
    return create_view(
        WinFormsTrayView,
        dispatch,
        loader=_load_winforms,
        destroy_icon=destroy_icon,
        api=api,
        dwmapi=dwmapi,
        platform=platform,
    )


class WinFormsTrayView:
    """Vista de bandeja con `NotifyIcon` y `ContextMenuStrip` propios."""

    def __init__(
        self,
        dispatch: Dispatch,
        *,
        api: _WinFormsApi,
        destroy_icon: Callable[[int], None] | None = None,
        dwmapi: Any = None,
        platform: str | None = None,
    ) -> None:
        self._dispatch = dispatch
        self._api = api
        self._icons = IconCache(api, destroy_icon=destroy_icon)
        self._dwmapi = dwmapi
        self._platform = platform if platform is not None else sys.platform
        self._lock = threading.Lock()
        self._form: Any = None
        self._notify: Any = None
        self._menu: Any = None
        self._desired: State = ([], "", (0, 0, 0), "")
        self._applied: StateSignature | None = None
        self._applied_menu: MenuSignature | None = None
        self._deferred_menu: MenuSignature | None = None
        self._stopped = False

    def run(self) -> None:
        """Crea la ventana oculta y el icono, y bloquea con el bombeo (hilo STA)."""
        api = self._api
        _co_initialize_apartment()
        try:
            form = create_host_form(api)
            notify = create_notify_icon(api, on_click=self._on_mouse_click)
            with self._lock:
                self._form = form
                self._notify = notify
                state = self._desired
                stopped = self._stopped
            if stopped:
                return
            # El primer estado se aplica en el propio hilo de la vista, antes del bombeo.
            self._apply_native(state)
            run_message_loop(api, form)
        # FRONTERA (bucle de la bandeja): este es el unico punto que corre dentro del
        # despacho nativo de WinForms y el hilo STA. Una excepcion que escape de aca no
        # rompe solo una fila del menu: retira el icono, y con la ventana oculta el usuario
        # pierde la unica forma de llegar a la app. Se registra con traza y el `finally`
        # libera los recursos igual.
        except Exception:
            _LOGGER.exception("The WinForms tray message loop failed.")
        finally:
            self._dispose_native()

    def stop(self) -> None:
        """Oculta el icono y cierra la ventana para que `run` retorne."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            form = self._form
        if form is not None:
            self._marshal(form, lambda: self._close_native(form))

    def _close_native(self, form: Any) -> None:
        """Oculta el icono y cierra la ventana en el hilo de la vista."""
        with self._lock:
            notify = self._notify
        if notify is not None:
            notify.Visible = False
        form.Close()

    def apply(
        self,
        spec: list[TrayMenuEntry],
        title: str,
        rgb: tuple[int, int, int],
        theme: str,
    ) -> None:
        """Aplica el estado desde cualquier hilo, marshando al hilo de la vista."""
        state: State = (list(spec), title, tuple(rgb), str(theme or ""))
        signature = state_signature(state[0], state[1], state[2], state[3])
        with self._lock:
            self._desired = state
            if self._stopped:
                return
            form = self._form
            if signature == self._applied and self._deferred_menu is None:
                return
        if form is None:
            # La vista todavia no arranco: `run` aplica el estado al crear el icono.
            return
        self._marshal(form, lambda: self._apply_native(state))

    def _apply_native(self, state: State) -> None:
        """Aplica el estado en el hilo de la vista; solo el rebuild se difiere (T-3.6)."""
        spec, title, rgb, theme = state
        signature = state_signature(spec, title, rgb, theme)
        menu_key = menu_signature(spec, theme)
        with self._lock:
            if signature == self._applied and self._deferred_menu is None:
                return
            notify, menu = self._notify, self._menu
            rebuild = menu_key != self._applied_menu
            displayed = bool(getattr(menu, "Visible", False)) if menu is not None else False
            icon_changed = self._icons.current_rgb != tuple(rgb)
        if notify is None:
            return
        try:
            icon = self._icon_for(rgb) if icon_changed else None
            apply_notify_state(notify, title=title, icon=icon)
        # Tooltip e icono son propiedades de .NET (`NotifyIcon.Text`/`Icon`), asi que solo
        # fallan con `clr_errors`; la vista se refresca de nuevo en el proximo cambio.
        except clr_errors(self._api):
            _LOGGER.exception("Failed to update the tray icon.")
            return
        if rebuild and displayed:
            # Solo la reconstruccion se difiere: el icono y el tooltip ya quedaron al dia.
            with self._lock:
                first_attempt = menu_key != self._deferred_menu
                self._deferred_menu = menu_key
            if first_attempt:
                log_applied_menu(spec, deferred=True)
            return
        try:
            new_menu = self._build_menu(spec, resolve_palette(theme)) if rebuild else menu
            if rebuild:
                notify.ContextMenuStrip = new_menu
        # Construir el `ContextMenuStrip` cruza a .NET: si falla, el menu anterior sigue
        # asignado y no se pierde ninguna accion.
        except clr_errors(self._api):
            _LOGGER.exception("Failed to apply the tray menu.")
            return
        with self._lock:
            previous = self._menu
            if rebuild:
                self._menu = new_menu
                self._applied_menu = menu_key
            self._applied = signature
            self._deferred_menu = None
        if rebuild:
            if previous is not None:
                _dispose_menu(previous, self._api)
            log_applied_menu(spec)

    def _build_menu(self, spec: Sequence[TrayMenuEntry], palette: TrayPalette) -> Any:
        """Crea el `ContextMenuStrip` completo con la paleta del tema activo."""
        return build_context_menu(
            spec,
            palette,
            self._dispatch,
            api=self._api,
            chrome=self._apply_menu_chrome,
        )

    def _apply_menu_chrome(self, control: Any) -> None:
        """Esquinas modernas y sin borde del sistema; cada paso degrada por separado."""
        apply_menu_chrome(control, self._api, dwmapi=self._dwmapi, platform=self._platform)

    def _icon_for(self, rgb: tuple[int, int, int]) -> Any:
        """Icono cacheado por color: un refresco con el mismo tinte no asigna nada nuevo."""
        return self._icons.icon_for(rgb)

    def _on_mouse_click(self, sender: Any, event_args: Any) -> None:
        """Clic izquierdo sobre el icono: despacha la accion por defecto del modelo."""
        try:
            if event_args.Button != self._api.forms.MouseButtons.Left:
                return
        # Leer el boton del evento solo falla con un fallo de binding de pythonnet (o de un
        # doble de prueba); sin boton legible no se despacha nada.
        except (AttributeError, TypeError):
            _LOGGER.debug("Tray mouse event without a button could not be read.", exc_info=True)
            return
        with self._lock:
            spec = list(self._desired[0])
        target = default_entry_target(spec)
        if target is not None:
            self._dispatch(target[0], target[1])

    def _marshal(self, form: Any, action: Callable[[], None]) -> None:
        """Ejecuta `action` en el hilo del bucle de mensajes de la vista."""
        invoke_on_ui_thread(self._api, form, action)

    def _dispose_native(self) -> None:
        """Libera icono, menu, `HICON` y la ventana en el hilo de la vista."""
        with self._lock:
            form, notify, menu = self._form, self._notify, self._menu
            self._form = self._notify = self._menu = None
            self._applied_menu = None
        dispose_notify(notify, self._api)
        if menu is not None:
            _dispose_menu(menu, self._api)
        self._icons.dispose()
        dispose_host(self._api, form)
