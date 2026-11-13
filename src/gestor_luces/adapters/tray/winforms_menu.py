"""Construccion del `ContextMenuStrip` de la bandeja a partir del modelo `TrayMenuEntry`.

Traduce el modelo puro (`menu_model.py`) a items reales de WinForms: hojas con su accion,
submenus (`DropDownItems`, que WinForms despliega al pasar el cursor) y separadores nativos.
Aqui viven tambien las firmas que deciden cuando hay que reconstruir el menu, el enganche de
los handlers de clic y de `ToolStripItem.Paint`, y el acabado de ventana de cada menu y
submenu (preferencia de esquina de DWM mas `Region` redondeada recortada 1 px, provista por
`winforms_paint`).

Es pura respecto del icono y de la ventana: no crea el `NotifyIcon` ni toca hilos, solo
objetos `ToolStripMenuItem`/`ToolStripSeparator` y ventanas de menu, de modo que las pruebas
pueden verificar el arbol, los colores y las esquinas sin escritorio.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from gestor_luces.adapters.platform.windows.window_chrome import _apply_corner_preference
from gestor_luces.adapters.tray.menu_model import TrayMenuEntry
from gestor_luces.adapters.tray.tray_view import Dispatch, resolve_entry_action
from gestor_luces.adapters.tray.winforms_host import (
    _load_winforms,
    _WinFormsApi,
    release_native,
)
from gestor_luces.adapters.tray.winforms_paint import (
    MENU_ITEM_PADDING_VERTICAL,
    TrayPalette,
    _color,
    apply_menu_region,
    paint_menu_item,
    paint_menu_separator,
)

_LOGGER = logging.getLogger(__name__)

#: Firma que obliga a reconstruir el `ContextMenuStrip`.
MenuSignature = tuple[tuple[TrayMenuEntry, ...], str]
#: Firma del estado completo, incluidos tooltip y tinte del icono.
StateSignature = tuple[MenuSignature, str, tuple[int, int, int]]


def menu_signature(spec: Sequence[TrayMenuEntry], theme: str) -> MenuSignature:
    """Firma del menu: todo lo que obliga a reconstruir el `ContextMenuStrip`."""
    return (tuple(spec), str(theme or ""))


def state_signature(
    spec: Sequence[TrayMenuEntry],
    title: str,
    rgb: tuple[int, int, int],
    theme: str,
) -> StateSignature:
    """Firma del estado completo; un cambio de tooltip o de tinte solo toca el icono."""
    return (menu_signature(spec, theme), str(title), tuple(rgb))


def default_entry_target(spec: Sequence[TrayMenuEntry]) -> tuple[str, Any] | None:
    """Accion que despacha un clic sobre el icono: la de la entrada por defecto del modelo."""
    for entry in spec:
        if entry.is_default:
            return resolve_entry_action(entry)
    return None


def _item_draw_width(sender: Any) -> int:
    """Ancho visible de la fila: el item puede sobresalir del menu por su propio padding."""
    width = int(getattr(sender, "Width", 0) or 0)
    try:
        owner = sender.Owner
        owner_width = int(owner.Width) - int(sender.Bounds.X)
    # Leer `Owner`/`Width`/`Bounds` de un item sin menu desplegado (o de un doble de
    # prueba) solo puede fallar con un fallo de binding de pythonnet.
    except (AttributeError, TypeError, ValueError, OverflowError):
        owner_width = width
    if owner_width > 0:
        width = min(width, owner_width)
    return max(1, width)


def _paint_quietly(paint: Callable[[], None]) -> None:
    """Dibuja una fila del menu sin dejar que el fallo llegue al bucle nativo.

    FRONTERA: `ToolStripItem.Paint` corre dentro del despacho de .NET; una excepcion que
    escape de un handler de evento llega al bombeo de mensajes y se lleva la bandeja. El
    dibujo es cosmetico (T-3.9): si falla, la fila conserva el fondo del renderer y el menu
    sigue funcionando, con la traza en el log. Es el unico guardia de los painters: lo
    comparten las filas y los separadores.
    """
    try:
        paint()
    except Exception:
        _LOGGER.debug("Tray menu paint failed.", exc_info=True)


def _item_paint_handler(
    palette: TrayPalette,
    api: _WinFormsApi,
    *,
    has_children: bool,
) -> Callable[..., None]:
    """Handler de `ToolStripItem.Paint` de una fila del menu."""

    def _on_paint(sender: Any, event_args: Any) -> None:
        def _paint() -> None:
            paint_menu_item(
                event_args.Graphics,
                palette=palette,
                api=api,
                text=str(sender.Text),
                font=sender.Font,
                width=_item_draw_width(sender),
                height=int(sender.Height),
                hovered=bool(sender.Selected or sender.Pressed),
                enabled=bool(sender.Enabled),
                checked=bool(sender.Checked),
                has_children=has_children,
            )

        _paint_quietly(_paint)

    return _on_paint


def _separator_paint_handler(palette: TrayPalette, api: _WinFormsApi) -> Callable[..., None]:
    """Handler de `ToolStripItem.Paint` de un separador."""

    def _on_paint(sender: Any, event_args: Any) -> None:
        def _paint() -> None:
            paint_menu_separator(
                event_args.Graphics,
                palette=palette,
                api=api,
                width=_item_draw_width(sender),
                height=int(sender.Height),
            )

        _paint_quietly(_paint)

    return _on_paint


def _click_handler(dispatch: Dispatch, action_id: str, payload: Any) -> Callable[..., None]:
    """Handler de clic de una hoja: entrega la accion al controlador de bandeja."""

    def _on_click(sender: Any, event_args: Any) -> None:
        dispatch(action_id, payload)

    return _on_click


def _build_menu_items(
    spec: Sequence[TrayMenuEntry],
    palette: TrayPalette,
    dispatch: Dispatch,
    *,
    api: _WinFormsApi | None = None,
) -> list[Any]:
    """Traduce el modelo puro a items reales de WinForms con la paleta aplicada.

    Es pura respecto del icono: no crea la ventana ni toca el `NotifyIcon`, solo objetos
    `ToolStripMenuItem`/`ToolStripSeparator`, de modo que las pruebas pueden verificar el
    arbol y los colores sin escritorio.
    """
    resolved = api or _load_winforms()
    if resolved is None:
        raise RuntimeError("WinForms is not available in this environment")
    return [
        _build_menu_item(
            entry,
            palette,
            dispatch,
            resolved,
            background=palette.background,
        )
        for entry in spec
    ]


def _build_menu_item(
    entry: TrayMenuEntry,
    palette: TrayPalette,
    dispatch: Dispatch,
    api: _WinFormsApi,
    *,
    background: str,
) -> Any:
    """Construye un item (hoja, padre de submenu o separador) con sus colores."""
    if entry.is_separator:
        separator = api.forms.ToolStripSeparator()
        separator.Paint += _separator_paint_handler(palette, api)
        return separator
    item = api.forms.ToolStripMenuItem(entry.label)
    item.BackColor = _color(background, api)
    item.ForeColor = _color(palette.text if entry.enabled else palette.disabled_text, api)
    item.Enabled = entry.enabled
    item.CheckOnClick = False
    # Filas altas: el alto de fuente (~20 px) mas este padding da los ~28 px modernos.
    item.Padding = api.forms.Padding(
        0,
        MENU_ITEM_PADDING_VERTICAL,
        0,
        MENU_ITEM_PADDING_VERTICAL,
    )
    if entry.checked is not None:
        item.Checked = bool(entry.checked)
    item.Paint += _item_paint_handler(palette, api, has_children=bool(entry.children))
    if entry.children:
        # Submenu real: WinForms lo despliega al pasar el cursor. No hay handler de clic en
        # el padre (un clic no debe abrir ni cerrar nada a mano).
        dropdown = item.DropDown
        dropdown.BackColor = _color(palette.background, api)
        dropdown.ForeColor = _color(palette.text, api)
        dropdown.ShowCheckMargin = False
        dropdown.ShowImageMargin = False
        for child in entry.children:
            dropdown.Items.Add(
                _build_menu_item(
                    child,
                    palette,
                    dispatch,
                    api,
                    background=palette.background,
                )
            )
        return item
    target = resolve_entry_action(entry)
    if target is not None and entry.enabled:
        action_id, payload = target
        item.Click += _click_handler(dispatch, action_id, payload)
    return item


def build_context_menu(
    spec: Sequence[TrayMenuEntry],
    palette: TrayPalette,
    dispatch: Dispatch,
    *,
    api: _WinFormsApi,
    chrome: Callable[[Any], None],
) -> Any:
    """Crea el `ContextMenuStrip` completo con la paleta del tema activo.

    `System`: el renderer del sistema pinta el fondo del dropdown con `BackColor` (el
    renderer profesional pinta una banda en el margen de imagen y degradados claros en la
    seleccion, imposibles de recolorear sin subclasificar el renderer). Las filas, el hover
    y los separadores los dibuja la vista en `ToolStripItem.Paint`.
    """
    menu = api.forms.ContextMenuStrip()
    menu.RenderMode = api.forms.ToolStripRenderMode.System
    menu.BackColor = _color(palette.background, api)
    menu.ForeColor = _color(palette.text, api)
    menu.ShowCheckMargin = False
    menu.ShowImageMargin = False
    for item in _build_menu_items(spec, palette, dispatch, api=api):
        menu.Items.Add(item)
    attach_menu_chrome(menu, chrome)
    return menu


def attach_menu_chrome(control: Any, chrome: Callable[[Any], None]) -> None:
    """Engancha el acabado de ventana (`chrome`) a cada menu, incluidos los submenus."""

    def _on_opened(sender: Any, event_args: Any) -> None:
        _apply_chrome_quietly(chrome, sender)

    try:
        control.Opened += _on_opened
    # Enganchar el evento de un control que no es un menu solo puede fallar con un fallo de
    # binding de pythonnet; sin el enganche el menu se muestra sin esquinas modernas.
    except (AttributeError, TypeError):
        _LOGGER.debug("Tray menu Opened hook failed.", exc_info=True)
    for item in list(getattr(control, "Items", [])):
        try:
            has_children = int(getattr(item, "DropDownItems", None).Count) > 0
        # Leer el arbol de items de un control que no es un menu solo falla con un fallo de
        # binding; sin hijos no hay submenu al que engancharle el acabado.
        except (AttributeError, TypeError, ValueError):
            has_children = False
        if not has_children:
            continue
        try:
            dropdown = item.DropDown
        # Un item cuyo `DropDown` no existe todavia se salta: el menu padre ya tiene su
        # propio `Opened`.
        except (AttributeError, TypeError):
            _LOGGER.debug("Tray submenu unavailable for its chrome.", exc_info=True)
            continue
        attach_menu_chrome(dropdown, chrome)


def _apply_chrome_quietly(chrome: Callable[[Any], None], control: Any) -> None:
    """Aplica el acabado del menu (DWM + `Region`) desde el evento `Opened` de .NET.

    FRONTERA: una excepcion que escape de un handler de `Opened` llega al bombeo de
    mensajes y se lleva la bandeja, y el acabado es cosmetico (T-3.9). Es el unico guardia
    de esta preocupacion: `attach_menu_chrome` engancha este mismo handler en el menu y en
    cada submenu, y cada paso degrada por dentro (`_apply_corner_preference` con
    `NATIVE_CALL_ERRORS`, `apply_menu_region` con `clr_errors`).
    """
    try:
        chrome(control)
    except Exception:
        _LOGGER.debug("Tray menu chrome failed.", exc_info=True)


def apply_menu_chrome(
    control: Any,
    api: _WinFormsApi,
    *,
    dwmapi: Any = None,
    platform: str | None = None,
) -> None:
    """Esquinas modernas y sin borde del sistema; cada paso degrada por separado.

    Se pide primero la preferencia de DWM. Como una region propia impide que DWM redondee
    la ventana, la region recortada 1 px es la que garantiza esquinas redondeadas (y
    elimina el borde de 1 px del renderer) en cualquier Windows; si la region no se puede
    crear, el menu sigue funcionando con el borde del sistema.
    """
    _apply_corner_preference(control, platform=platform, dwmapi=dwmapi)
    apply_menu_region(control, api)


def _dispose_menu(menu: Any, api: _WinFormsApi) -> None:
    """Descarta un menu que ya no se muestra."""
    release_native(menu.Dispose, api, what="Tray menu disposal")
