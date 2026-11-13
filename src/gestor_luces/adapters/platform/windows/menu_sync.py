"""Traduccion del modelo de menu puro a pywebview y sync en vivo del `MenuStrip` WinForms.

pywebview construye el menu una sola vez y no ofrece API de actualizacion, asi que tras
el arranque los objetos `ToolStripMenuItem` se actualizan en sitio (idioma, etiqueta de
mostrar/ocultar y el check de "Iniciar con Windows").
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gestor_luces.adapters.ui_webview.app_menu import AppMenu

_LOGGER = logging.getLogger(__name__)


def _to_webview_menus(
    spec: list[AppMenu],
    on_action: Any,
) -> list[Any]:
    """Translate the pure menu model into pywebview `Menu` objects."""
    from webview.menu import Menu, MenuAction, MenuSeparator

    menus: list[Any] = []
    for menu in spec:
        items: list[Any] = []
        for item in menu.items:
            if item.is_separator:
                items.append(MenuSeparator())
            else:
                items.append(
                    # Items from pywebview are not checkable: `_sync_native_menu` sets `Checked`.
                    MenuAction(item.label, lambda action_id=item.action_id: on_action(action_id))
                )
        menus.append(Menu(menu.title, items))
    return menus


def _sync_native_menu(window: Any, spec: list[AppMenu]) -> None:
    """Push labels and check marks onto the live WinForms `MenuStrip` created by pywebview.

    pywebview builds the menu once and offers no update API, so after startup the
    `ToolStripMenuItem` objects are updated in place (language, show/hide label and the
    Start with Windows check mark). Failures are logged and never propagate.
    """
    if sys.platform != "win32":
        return
    native_form = getattr(window, "native", None)
    if native_form is None:
        return
    if bool(getattr(native_form, "IsDisposed", False)) or not bool(
        getattr(native_form, "IsHandleCreated", True)
    ):
        return

    def _apply() -> None:
        if bool(getattr(native_form, "IsDisposed", False)) or not bool(
            getattr(native_form, "IsHandleCreated", True)
        ):
            return
        strip = next(
            (c for c in native_form.Controls if c.GetType().Name == "MenuStrip"),
            None,
        )
        if strip is None:
            return
        for top_index, menu in enumerate(spec):
            top_item = strip.Items[top_index]
            top_item.Text = menu.title
            for sub_index, item in enumerate(menu.items):
                if item.is_separator:
                    continue
                native_item = top_item.DropDownItems[sub_index]
                native_item.Text = item.label
                if item.checked is not None:
                    native_item.Checked = bool(item.checked)

    try:
        from System import Action

        if native_form.InvokeRequired:
            native_form.Invoke(Action(_apply))
        else:
            _apply()
    # FRONTERA: este sync cruza a WinForms con pythonnet (`System.Action`, propiedades de
    # `ToolStripMenuItem`, `Control.Invoke`), que no garantiza el tipo de excepcion del CLR.
    # Es una actualizacion cosmetica de etiquetas y tildes: se loguea con traza y el menu
    # se queda como estaba en vez de romper el hilo que serializa los refrescos.
    except Exception:
        _LOGGER.debug("Native menu sync skipped.", exc_info=True)
