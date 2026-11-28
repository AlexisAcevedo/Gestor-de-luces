"""Traduccion del modelo de menu puro a pywebview y sync en vivo del `MenuStrip` WinForms.

pywebview construye el menu una sola vez y no ofrece API de actualizacion, asi que tras
el arranque los objetos `ToolStripMenuItem` se actualizan en sitio (idioma, etiqueta de
mostrar/ocultar y el check de "Iniciar con Windows"). Tambien aplica la paleta clara/oscura
sobre el `MenuStrip` con `ToolStripItem.Paint` (sin subclasificar `ProfessionalColorTable`,
ya que pythonnet 3.2.1 no emite tipos derivados con despacho virtual).
"""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import TYPE_CHECKING, Any

from wiz_console.adapters.tray.winforms_host import _load_winforms, _WinFormsApi
from wiz_console.adapters.tray.winforms_menu import apply_menu_chrome
from wiz_console.adapters.tray.winforms_paint import (
    TrayPalette,
    _color,
    item_paint_style,
    paint_menu_item,
    paint_menu_separator,
    resolve_palette,
)

if TYPE_CHECKING:
    from wiz_console.adapters.ui_webview.app_menu import AppMenu

_LOGGER = logging.getLogger(__name__)

# Mutable per-strip theme state keyed by id(strip) so Paint/Opened handlers bind once
# and always draw with the latest palette without duplicating event subscriptions.
_THEMED_STRIPS: dict[int, dict[str, Any]] = {}


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


def _paint_top_menu_item(
    graphics: Any,
    *,
    palette: TrayPalette,
    api: _WinFormsApi,
    text: str,
    font: Any,
    width: int,
    height: int,
    hovered: bool,
) -> None:
    """Paint a top-level MenuStrip entry (e.g. File / Help) with centered palette text."""
    drawing = api.drawing
    style = item_paint_style(palette, hovered=hovered, enabled=True)
    background = drawing.SolidBrush(_color(style.background, api))
    try:
        graphics.FillRectangle(background, drawing.Rectangle(0, 0, max(1, width), max(1, height)))
    finally:
        background.Dispose()
    foreground = drawing.SolidBrush(_color(style.text, api))
    line_format = drawing.StringFormat()
    try:
        line_format.Alignment = drawing.StringAlignment.Center
        line_format.LineAlignment = drawing.StringAlignment.Center
        line_format.FormatFlags = drawing.StringFormatFlags.NoWrap
        graphics.DrawString(
            text,
            font,
            foreground,
            drawing.RectangleF(0, 0, max(1, width), max(1, height)),
            line_format,
        )
    finally:
        line_format.Dispose()
        foreground.Dispose()


def _is_separator_item(item: Any, api: _WinFormsApi) -> bool:
    sep_type = getattr(api.forms, "ToolStripSeparator", None)
    if isinstance(sep_type, type) and isinstance(item, sep_type):
        return True
    get_type = getattr(item, "GetType", None)
    if callable(get_type):
        try:
            return getattr(get_type(), "Name", "") == "ToolStripSeparator"
        except Exception:
            return False
    return False


def _apply_menu_strip_theme(
    strip: Any,
    theme: str,
    *,
    api: _WinFormsApi | None = None,
) -> bool:
    """Apply the active light/dark TrayPalette onto an existing WinForms `MenuStrip`."""
    resolved = api or _load_winforms()
    if resolved is None or strip is None:
        return False

    palette = resolve_palette(theme)
    bg_color = _color(palette.background, resolved)
    fg_color = _color(palette.text, resolved)
    disabled_color = _color(palette.disabled_text, resolved)

    strip.RenderMode = resolved.forms.ToolStripRenderMode.System
    strip.BackColor = bg_color
    strip.ForeColor = fg_color

    strip_key = id(strip)
    state = _THEMED_STRIPS.get(strip_key)
    if state is None:
        state = {
            "palette": palette,
            "hooked_items": set(),
            "hooked_dropdowns": set(),
            "disposed_hooked": False,
        }
        _THEMED_STRIPS[strip_key] = state
    state["palette"] = palette

    if not state["disposed_hooked"]:
        state["disposed_hooked"] = True
        with contextlib.suppress(AttributeError, TypeError):
            strip.Disposed += lambda _s, _e, k=strip_key: _THEMED_STRIPS.pop(k, None)

    for top_item in list(getattr(strip, "Items", [])):
        top_item.BackColor = bg_color
        top_item.ForeColor = fg_color
        top_key = id(top_item)
        if top_key not in state["hooked_items"]:
            state["hooked_items"].add(top_key)

            def _on_top_paint(sender: Any, event_args: Any, st: dict[str, Any] = state) -> None:
                try:
                    dropdown_obj = getattr(sender, "DropDown", None)
                    hovered = bool(
                        getattr(sender, "Selected", False)
                        or getattr(sender, "Pressed", False)
                        or getattr(dropdown_obj, "Visible", False)
                    )
                    _paint_top_menu_item(
                        event_args.Graphics,
                        palette=st["palette"],
                        api=resolved,
                        text=str(sender.Text),
                        font=sender.Font,
                        width=int(getattr(sender, "Width", 1) or 1),
                        height=int(getattr(sender, "Height", 1) or 1),
                        hovered=hovered,
                    )
                except Exception:
                    _LOGGER.debug("MenuStrip top-item paint failed.", exc_info=True)

            top_item.Paint += _on_top_paint

        dropdown = getattr(top_item, "DropDown", None)
        if dropdown is not None:
            with contextlib.suppress(AttributeError, TypeError):
                dropdown.RenderMode = resolved.forms.ToolStripRenderMode.System
            dropdown.BackColor = bg_color
            dropdown.ForeColor = fg_color
            dropdown.ShowCheckMargin = False
            dropdown.ShowImageMargin = False
            dd_key = id(dropdown)
            if dd_key not in state["hooked_dropdowns"]:
                state["hooked_dropdowns"].add(dd_key)

                def _on_opened(sender: Any, _event_args: Any) -> None:
                    try:
                        apply_menu_chrome(sender, resolved)
                    except Exception:
                        _LOGGER.debug("MenuStrip dropdown chrome failed.", exc_info=True)

                with contextlib.suppress(AttributeError, TypeError):
                    dropdown.Opened += _on_opened

        for sub_item in list(getattr(top_item, "DropDownItems", [])):
            sub_key = id(sub_item)
            if _is_separator_item(sub_item, resolved):
                if sub_key not in state["hooked_items"]:
                    state["hooked_items"].add(sub_key)

                    def _on_sep_paint(
                        sender: Any, event_args: Any, st: dict[str, Any] = state
                    ) -> None:
                        try:
                            paint_menu_separator(
                                event_args.Graphics,
                                palette=st["palette"],
                                api=resolved,
                                width=int(getattr(sender, "Width", 1) or 1),
                                height=int(getattr(sender, "Height", 1) or 1),
                            )
                        except Exception:
                            _LOGGER.debug("MenuStrip separator paint failed.", exc_info=True)

                    sub_item.Paint += _on_sep_paint
                continue

            sub_item.BackColor = bg_color
            sub_item.ForeColor = (
                fg_color if bool(getattr(sub_item, "Enabled", True)) else disabled_color
            )
            if sub_key not in state["hooked_items"]:
                state["hooked_items"].add(sub_key)

                def _on_sub_paint(sender: Any, event_args: Any, st: dict[str, Any] = state) -> None:
                    try:
                        paint_menu_item(
                            event_args.Graphics,
                            palette=st["palette"],
                            api=resolved,
                            text=str(sender.Text),
                            font=sender.Font,
                            width=int(getattr(sender, "Width", 1) or 1),
                            height=int(getattr(sender, "Height", 1) or 1),
                            hovered=bool(
                                getattr(sender, "Selected", False)
                                or getattr(sender, "Pressed", False)
                            ),
                            enabled=bool(getattr(sender, "Enabled", True)),
                            checked=bool(getattr(sender, "Checked", False)),
                            has_children=False,
                        )
                    except Exception:
                        _LOGGER.debug("MenuStrip item paint failed.", exc_info=True)

                sub_item.Paint += _on_sub_paint

    invalidate = getattr(strip, "Invalidate", None)
    if callable(invalidate):
        invalidate(True)
    return True


def _sync_native_menu_theme(
    window: Any,
    theme: str,
    *,
    api: _WinFormsApi | None = None,
) -> bool:
    """Apply explicit palette styling onto the live WinForms `MenuStrip` when available."""
    if sys.platform != "win32":
        return False
    native_form = getattr(window, "native", None)
    if native_form is None:
        return False
    if bool(getattr(native_form, "IsDisposed", False)) or not bool(
        getattr(native_form, "IsHandleCreated", True)
    ):
        return False

    applied = False

    def _apply() -> None:
        nonlocal applied
        if bool(getattr(native_form, "IsDisposed", False)) or not bool(
            getattr(native_form, "IsHandleCreated", True)
        ):
            return
        strip = next(
            (c for c in list(native_form.Controls) if c.GetType().Name == "MenuStrip"),
            None,
        )
        if strip is None:
            return
        applied = _apply_menu_strip_theme(strip, theme, api=api)

    try:
        from System import Action

        if native_form.InvokeRequired:
            native_form.Invoke(Action(_apply))
        else:
            _apply()
    except Exception:
        _LOGGER.debug("Native menu theme sync skipped.", exc_info=True)
        return False
    return applied


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
        # Materializado a proposito: `Controls` es una coleccion de .NET y el `next` sobre un
        # iterador vivo ve la coleccion cambiar bajo sus pies cuando la ventana se esta
        # cerrando en el mismo hilo (`InvalidOperationException: Coleccion modificada`).
        strip = next(
            (c for c in list(native_form.Controls) if c.GetType().Name == "MenuStrip"),
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
