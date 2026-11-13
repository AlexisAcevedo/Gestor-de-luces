"""Vista de bandeja basada en `pystray`, respaldo de la vista WinForms.

Conserva el comportamiento historico del adapter: menu clasico de Win32, icono con
tooltip e imagen teñida, popup mostrado por la ventana del icono (para que los submenus
se desplieguen al pasar el cursor, T-3.7) y rebuild del `HMENU` diferido mientras hay un
menu desplegado (T-3.6).
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from collections.abc import Callable
from typing import Any

import pystray
from PIL import Image

from gestor_luces.adapters.platform.windows.menu_state import _is_menu_open
from gestor_luces.adapters.platform.windows.window_chrome import NATIVE_CALL_ERRORS
from gestor_luces.adapters.tray.menu_model import TrayMenuEntry
from gestor_luces.adapters.tray.tray_view import (
    ICON_NAME,
    Dispatch,
    TrayView,
    log_applied_menu,
    render_icon_image,
    resolve_entry_action,
)

_LOGGER = logging.getLogger(__name__)

IconFactory = Callable[[str, Image.Image, str, pystray.Menu], Any]
MenuIsOpen = Callable[[], bool]

#: Estado nativo vigente: modelo de menu, tooltip y color del icono.
State = tuple[list[TrayMenuEntry], str, tuple[int, int, int]]


def create_pystray_view(
    dispatch: Dispatch,
    *,
    icon_factory: IconFactory | None = None,
    menu_is_open: MenuIsOpen | None = None,
) -> TrayView:
    """Crea la vista de respaldo basada en `pystray`."""
    return PystrayTrayView(dispatch, icon_factory=icon_factory, menu_is_open=menu_is_open)


def _default_icon_factory(
    name: str,
    image: Image.Image,
    title: str,
    menu: pystray.Menu,
) -> Any:
    """Crea el icono nativo, con el popup del menu corregido en Windows cuando se puede."""
    icon_class = _owner_popup_icon_class()
    if icon_class is not None:
        try:
            return icon_class(name, image, title, menu)
        # Construir el icono Win32 cruza a `ctypes`: solo falla con `NATIVE_CALL_ERRORS`.
        except NATIVE_CALL_ERRORS:
            _LOGGER.debug("Owned-popup icon unavailable; using the stock icon.", exc_info=True)
    return pystray.Icon(name, image, title, menu)


_OWNER_POPUP_ICON_CLASS: Any = None
_OWNER_POPUP_ICON_CLASS_READY = False


def _owner_popup_icon_class() -> Any:
    """Clase de icono cuya ventana propia es tambien dueña del popup (Windows).

    `pystray 0.19.5` muestra el menu con `TrackPopupMenuEx` pasando `self._menu_hwnd`: una
    segunda ventana invisible que nunca llega a ser la ventana en primer plano (pystray
    activa `_hwnd` con `SetForegroundWindow`). Con ese owner, Windows no auto-despliega
    los submenus al pasar el cursor: hay que hacer clic. Pasar la ventana ya activada
    devuelve el comportamiento nativo de cualquier menu de Windows.

    Se construye una sola vez y se cachea. Si `pystray` cambia sus internals, el import
    falla, se devuelve None y la vista usa el icono estandar sin romperse.
    """
    global _OWNER_POPUP_ICON_CLASS, _OWNER_POPUP_ICON_CLASS_READY
    if _OWNER_POPUP_ICON_CLASS_READY:
        return _OWNER_POPUP_ICON_CLASS
    _OWNER_POPUP_ICON_CLASS_READY = True
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        from pystray._util import win32
        from pystray._win32 import Icon as _Win32Icon
    # Los internals de `pystray` solo pueden faltar con un `ImportError` (o un
    # `AttributeError` si el modulo existe pero cambia el nombre): sin ellos se usa el
    # icono estandar y el hover sigue necesitando clic.
    except (ImportError, AttributeError):
        _LOGGER.debug("Owned-popup icon unavailable; menu hover stays click-only.", exc_info=True)
        return None

    class _OwnerPopupIcon(_Win32Icon):
        """Icono cuyo popup se muestra con la ventana del icono como dueña."""

        def _on_notify(self, wparam: int, lparam: int) -> None:
            menu_handle = getattr(self, "_menu_handle", None)
            if lparam != win32.WM_RBUTTONUP or not menu_handle:
                super()._on_notify(wparam, lparam)
                return
            win32.SetForegroundWindow(self._hwnd)
            point = wintypes.POINT()
            win32.GetCursorPos(ctypes.byref(point))
            hmenu, descriptors = menu_handle
            index = win32.TrackPopupMenuEx(
                hmenu,
                win32.TPM_RIGHTALIGN | win32.TPM_BOTTOMALIGN | win32.TPM_RETURNCMD,
                point.x,
                point.y,
                self._hwnd,
                None,
            )
            if index > 0:
                descriptors[index - 1](self)

    _OWNER_POPUP_ICON_CLASS = _OwnerPopupIcon
    return _OWNER_POPUP_ICON_CLASS


def _constant(value: bool) -> Callable[[Any], bool]:
    """Envuelve un booleano porque pystray exige callables para `checked`."""
    return lambda _item: value


def _signature(state: State) -> tuple[Any, ...]:
    """Huella del estado nativo para descartar reaplicaciones identicas."""
    spec, title, rgb = state
    return (tuple(spec), title, tuple(rgb))


class PystrayTrayView:
    """Vista de bandeja sobre `pystray.Icon` (respaldo si WinForms no carga)."""

    def __init__(
        self,
        dispatch: Dispatch,
        *,
        icon_factory: IconFactory | None = None,
        menu_is_open: MenuIsOpen | None = None,
    ) -> None:
        self._dispatch = dispatch
        self._icon_factory = icon_factory or _default_icon_factory
        self._menu_is_open = menu_is_open or _is_menu_open
        self._lock = threading.Lock()
        self._create_lock = threading.Lock()
        self._icon: Any = None
        self._stopped = False
        self._spec: list[TrayMenuEntry] = []
        self._title = ""
        self._rgb: tuple[int, int, int] = (0, 0, 0)
        self._applied: tuple[Any, ...] | None = None
        self._deferred: State | None = None

    def run(self) -> None:
        """Crea el icono (si falta) y bloquea el hilo llamador con el bombeo de mensajes."""
        icon = self._ensure_icon()
        with self._lock:
            if self._stopped:
                return
        icon.run()

    def stop(self) -> None:
        """Retira el icono; pystray acepta `stop` desde cualquier hilo."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            icon = self._icon
        if icon is None:
            return
        try:
            icon.stop()
        # `pystray` detiene el icono con llamadas Win32 a traves de `ctypes`.
        except NATIVE_CALL_ERRORS:
            _LOGGER.exception("Failed to stop the pystray icon.")

    def apply(
        self,
        spec: list[TrayMenuEntry],
        title: str,
        rgb: tuple[int, int, int],
        theme: str,
    ) -> None:
        """Aplica el estado; `theme` se acepta por contrato pero pystray no colorea menus."""
        state: State = (list(spec), title, tuple(rgb))
        with self._lock:
            self._spec, self._title, self._rgb = state[0], state[1], state[2]
            if self._stopped:
                return
            already_applied = (
                self._icon is not None
                and _signature(state) == self._applied
                and self._deferred is None
            )
        if already_applied:
            return
        # El objeto `Icon` se crea sin abrir ninguna ventana, asi que puede existir antes de
        # que arranque el bombeo. El estado nativo si se aplica en cada cambio.
        icon = self._ensure_icon()
        self._apply_native(icon, state)

    def _ensure_icon(self) -> Any:
        """Crea el `pystray.Icon` una sola vez, con el estado vigente."""
        with self._create_lock:
            with self._lock:
                if self._icon is not None:
                    return self._icon
                spec, title, rgb = self._spec, self._title, self._rgb
            # El descriptor se evalua en cada rebuild, de modo que `update_menu()` siempre
            # lee el modelo cacheado y no una copia obsoleta.
            menu = pystray.Menu(self._current_menu_items)
            icon = self._icon_factory(ICON_NAME, render_icon_image(rgb), title, menu)
            with self._lock:
                self._icon = icon
                self._applied = _signature((spec, title, rgb))
                self._deferred = None
            return icon

    def _apply_native(self, icon: Any, state: State) -> None:
        """Actualiza imagen, tooltip y `HMENU` desde el hilo de refresco del controlador."""
        if self._menu_is_open():
            # Destruir el HMENU con el popup abierto invalida sus IDs y submenus: el rebuild
            # queda pendiente y el proximo `apply` lo reintenta cuando el menu se cierra.
            with self._lock:
                first_attempt = self._deferred != state
                self._deferred = state
            if first_attempt:
                log_applied_menu(state[0], deferred=True)
            return
        spec, title, rgb = state
        try:
            icon.icon = render_icon_image(rgb)
            icon.title = title
        # Imagen y tooltip son del icono Win32 de `pystray` (`ctypes` + PIL).
        except NATIVE_CALL_ERRORS:
            _LOGGER.exception("Failed to update the tray icon image.")
        with self._lock:
            self._applied = _signature(state)
            self._deferred = None
        log_applied_menu(spec)
        try:
            icon.update_menu()
        # `update_menu` destruye y recrea el `HMENU` con llamadas Win32 de `ctypes`.
        except NATIVE_CALL_ERRORS:
            _LOGGER.exception("Failed to rebuild the pystray menu.")

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
        target = resolve_entry_action(entry)
        return pystray.MenuItem(
            entry.label,
            self._make_handler(*target) if target is not None and entry.enabled else None,
            checked=_constant(entry.checked) if entry.checked is not None else None,
            radio=entry.radio,
            default=entry.is_default,
            enabled=entry.enabled,
        )

    def _make_handler(self, action_id: str, payload: Any) -> Callable[[], None]:
        def _handler() -> None:
            self._dispatch(action_id, payload)

        return _handler
