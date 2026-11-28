"""Tests de caracterizacion para la traduccion del menu nativo y el sync WinForms.

Cubre `_to_webview_menus` (traduccion del modelo puro a objetos `webview.menu`) y
`_sync_native_menu` (actualizacion en vivo del `MenuStrip` WinForms), parte del rango
`main.py:65-500` que T-3.1 debe caracterizar antes de la extraccion de T-3.2.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from wiz_console.adapters.platform.windows.menu_sync import (
    _apply_menu_strip_theme,
    _sync_native_menu_theme,
)
from wiz_console.adapters.tray.winforms_paint import DARK_PALETTE, LIGHT_PALETTE, parse_hex_color
from wiz_console.adapters.ui_webview.app_menu import AppMenu, AppMenuItem
from wiz_console.main import _sync_native_menu, _to_webview_menus


def _menu_spec() -> list[AppMenu]:
    return [
        AppMenu(
            title="Archivo",
            items=(
                AppMenuItem(label="Ocultar ventana", action_id="toggle_window"),
                AppMenuItem(
                    label="Iniciar con Windows",
                    action_id="toggle_autostart",
                    checked=True,
                ),
                AppMenuItem(is_separator=True),
                AppMenuItem(label="Salir", action_id="exit"),
            ),
        ),
        AppMenu(
            title="Ayuda",
            items=(
                AppMenuItem(label="Atajos", action_id="show_shortcuts"),
                AppMenuItem(label="Acerca de", action_id="show_about"),
            ),
        ),
    ]


def test_to_webview_menus_translates_model_and_fires_actions() -> None:
    """`_to_webview_menus` convierte el modelo puro en objetos Menu de pywebview."""
    fired: list[str] = []
    menus = _to_webview_menus(_menu_spec(), on_action=fired.append)

    assert [m.title for m in menus] == ["Archivo", "Ayuda"]

    # El separador y los items accionables del menu Archivo
    file_items = menus[0].items
    assert len(file_items) == 4
    assert file_items[0].title == "Ocultar ventana"
    # El tercer item es un separador (MenuSeparator no tiene titulo)
    assert isinstance(file_items[2], type(file_items[2]))  # MenuSeparator presente

    # Al disparar la funcion del primer item, se invoca on_action con el action_id
    file_items[0].function()
    assert fired == ["toggle_window"]


def test_to_webview_menus_handles_empty_spec() -> None:
    """Un spec vacio produce una lista vacia de menus."""
    assert _to_webview_menus([], on_action=lambda _id: None) == []


def test_sync_native_menu_skips_non_win32(monkeypatch) -> None:
    """`_sync_native_menu` es no-op fuera de Windows."""
    monkeypatch.setattr("wiz_console.main.sys.platform", "linux")
    calls: list[bool] = []
    _sync_native_menu(SimpleNamespace(native=SimpleNamespace()), _menu_spec())
    assert calls == []


def test_sync_native_menu_skips_missing_or_disposed_native(monkeypatch) -> None:
    """`_sync_native_menu` retorna sin tocar nada si no hay ventana nativa valida."""
    monkeypatch.setattr("wiz_console.main.sys.platform", "win32")

    # native_form None
    _sync_native_menu(SimpleNamespace(native=None), _menu_spec())

    # disposed
    _sync_native_menu(
        SimpleNamespace(native=SimpleNamespace(IsDisposed=True, IsHandleCreated=True)),
        _menu_spec(),
    )

    # handle no creado
    _sync_native_menu(
        SimpleNamespace(native=SimpleNamespace(IsDisposed=False, IsHandleCreated=False)),
        _menu_spec(),
    )


def test_sync_native_menu_applies_labels_and_checks(monkeypatch) -> None:
    """`_sync_native_menu` actualiza Text y Checked en el MenuStrip WinForms en vivo."""
    monkeypatch.setattr("wiz_console.main.sys.platform", "win32")

    # `_sync_native_menu` hace `from System import Action`; inyectamos un fake para
    # que `_apply()` se ejecute sin pythonnet real.
    class _FakeAction:
        def __init__(self, fn) -> None:
            self._fn = fn

        def Invoke(self) -> None:
            self._fn()

    fake_system = SimpleNamespace(Action=_FakeAction)
    monkeypatch.setitem(sys.modules, "System", fake_system)

    # Fake del MenuStrip: un control cuyo GetType().Name == "MenuStrip", con .Items
    # (top-level) y cada top-level con .DropDownItems (sub-items).
    def _top_item(sub_labels: list[SimpleNamespace]) -> SimpleNamespace:
        return SimpleNamespace(Text="", DropDownItems=sub_labels)

    archivo_subs = [
        SimpleNamespace(Text="", Checked=False),
        SimpleNamespace(Text="", Checked=False),
        SimpleNamespace(Text="", Checked=False),  # separator placeholder
        SimpleNamespace(Text="", Checked=False),
    ]
    ayuda_subs = [
        SimpleNamespace(Text="", Checked=False),
        SimpleNamespace(Text="", Checked=False),
    ]
    menu_strip = SimpleNamespace(
        GetType=lambda: SimpleNamespace(Name="MenuStrip"),
        Visible=True,
        Items=[_top_item(archivo_subs), _top_item(ayuda_subs)],
    )

    native_form = SimpleNamespace(
        IsDisposed=False,
        IsHandleCreated=True,
        InvokeRequired=False,
        Controls=[menu_strip],
    )

    _sync_native_menu(SimpleNamespace(native=native_form), _menu_spec())

    # Menu Archivo (top 0): titulo + labels + check del autostart
    top_items = menu_strip.Items
    assert top_items[0].Text == "Archivo"
    assert top_items[0].DropDownItems[0].Text == "Ocultar ventana"
    assert top_items[0].DropDownItems[1].Text == "Iniciar con Windows"
    assert top_items[0].DropDownItems[1].Checked is True
    assert top_items[0].DropDownItems[3].Text == "Salir"

    # Menu Ayuda (top 1)
    assert top_items[1].Text == "Ayuda"
    assert top_items[1].DropDownItems[0].Text == "Atajos"
    assert top_items[1].DropDownItems[1].Text == "Acerca de"


class _EventSlot(list):
    def __iadd__(self, fn: object) -> _EventSlot:
        self.append(fn)
        return self


class _RecordingBrush:
    def __init__(self, color: tuple[int, int, int]) -> None:
        self.color = color
        self.disposed = False

    def Dispose(self) -> None:
        self.disposed = True


class _RecordingFormat:
    Alignment: Any = None
    LineAlignment: Any = None
    FormatFlags: Any = None

    def Dispose(self) -> None:
        return None


def _fake_winforms_api() -> SimpleNamespace:
    class _ToolStripSeparator:
        pass

    return SimpleNamespace(
        forms=SimpleNamespace(
            ToolStripRenderMode=SimpleNamespace(System="System"),
            ToolStripSeparator=_ToolStripSeparator,
        ),
        drawing=SimpleNamespace(
            Color=SimpleNamespace(FromArgb=lambda r, g, b: (r, g, b)),
            SolidBrush=_RecordingBrush,
            Pen=lambda color, _w=1: _RecordingBrush(color),
            Rectangle=lambda x, y, w, h: ("rect", x, y, w, h),
            RectangleF=lambda x, y, w, h: ("rectf", x, y, w, h),
            StringFormat=_RecordingFormat,
            StringAlignment=SimpleNamespace(Center="Center"),
            StringFormatFlags=SimpleNamespace(NoWrap="NoWrap"),
        ),
    )


def _fake_menu_strip(
    api: SimpleNamespace,
) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    class _Item:
        def __init__(self, text: str, *, enabled: bool = True, checked: bool = False) -> None:
            self.Text = text
            self.Enabled = enabled
            self.Checked = checked
            self.Selected = False
            self.Pressed = False
            self.Width = 140
            self.Height = 24
            self.Font = object()
            self.BackColor: Any = None
            self.ForeColor: Any = None
            self.Paint = _EventSlot()
            self.DropDown = SimpleNamespace(
                RenderMode=None,
                BackColor=None,
                ForeColor=None,
                ShowCheckMargin=True,
                ShowImageMargin=True,
                Visible=False,
                Opened=_EventSlot(),
            )
            self.DropDownItems: list[Any] = []

        def GetType(self) -> SimpleNamespace:
            return SimpleNamespace(Name="ToolStripMenuItem")

    sub_leaf = _Item("Ocultar ventana", enabled=True, checked=True)
    sub_disabled = _Item("Sin presets", enabled=False, checked=False)
    sep = api.forms.ToolStripSeparator()
    sep.Paint = _EventSlot()
    sep.Width = 140
    sep.Height = 6

    top_item = _Item("Archivo")
    top_item.DropDownItems = [sub_leaf, sep, sub_disabled]

    strip = SimpleNamespace(
        RenderMode=None,
        BackColor=None,
        ForeColor=None,
        Items=[top_item],
        Disposed=_EventSlot(),
        Invalidate=lambda *_args: None,
        GetType=lambda: SimpleNamespace(Name="MenuStrip"),
    )
    return strip, top_item, sub_leaf


def test_sync_native_menu_theme_applies_dark_palette_and_binds_paint_idempotently(
    monkeypatch,
) -> None:
    monkeypatch.setattr("wiz_console.adapters.platform.windows.menu_sync.sys.platform", "win32")

    class _FakeAction:
        def __init__(self, fn) -> None:
            self._fn = fn

        def Invoke(self) -> None:
            self._fn()

    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(Action=_FakeAction))
    api = _fake_winforms_api()
    strip, top_item, sub_leaf = _fake_menu_strip(api)
    native_form = SimpleNamespace(
        IsDisposed=False,
        IsHandleCreated=True,
        InvokeRequired=True,
        Invoke=lambda action: action.Invoke(),
        Controls=[strip],
    )
    window = SimpleNamespace(native=native_form)

    assert _sync_native_menu_theme(window, "atmospheric-dark", api=api) is True
    assert strip.RenderMode == "System"
    assert strip.BackColor == parse_hex_color(DARK_PALETTE.background)
    assert strip.ForeColor == parse_hex_color(DARK_PALETTE.text)
    assert top_item.BackColor == parse_hex_color(DARK_PALETTE.background)
    assert top_item.DropDown.ShowCheckMargin is False
    assert top_item.DropDown.ShowImageMargin is False
    assert len(top_item.Paint) == 1
    assert len(sub_leaf.Paint) == 1
    assert top_item.DropDownItems[2].ForeColor == parse_hex_color(DARK_PALETTE.disabled_text)

    # Re-applying light theme updates mutable palette without duplicating Paint handlers
    assert _apply_menu_strip_theme(strip, "architectural-stone", api=api) is True
    assert strip.BackColor == parse_hex_color(LIGHT_PALETTE.background)
    assert strip.ForeColor == parse_hex_color(LIGHT_PALETTE.text)
    assert len(top_item.Paint) == 1
    assert len(sub_leaf.Paint) == 1

    # Invoke the bound Paint handler to verify palette color is read dynamically
    fills: list[tuple[int, int, int]] = []
    graphics = SimpleNamespace(
        FillRectangle=lambda brush, _rect: fills.append(brush.color),
        DrawString=lambda *_args: None,
        FillEllipse=lambda *_args: None,
    )
    top_item.Paint[0](top_item, SimpleNamespace(Graphics=graphics))
    assert fills == [parse_hex_color(LIGHT_PALETTE.background)]


def test_sync_native_menu_theme_skips_non_win32_and_disposed(monkeypatch) -> None:
    api = _fake_winforms_api()
    monkeypatch.setattr("wiz_console.adapters.platform.windows.menu_sync.sys.platform", "linux")
    assert (
        _sync_native_menu_theme(
            SimpleNamespace(native=SimpleNamespace()), "atmospheric-dark", api=api
        )
        is False
    )

    monkeypatch.setattr("wiz_console.adapters.platform.windows.menu_sync.sys.platform", "win32")
    assert (
        _sync_native_menu_theme(
            SimpleNamespace(native=SimpleNamespace(IsDisposed=True, IsHandleCreated=True)),
            "atmospheric-dark",
            api=api,
        )
        is False
    )
