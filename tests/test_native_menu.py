"""Tests de caracterizacion para la traduccion del menu nativo y el sync WinForms.

Cubre `_to_webview_menus` (traduccion del modelo puro a objetos `webview.menu`) y
`_sync_native_menu` (actualizacion en vivo del `MenuStrip` WinForms), parte del rango
`main.py:65-500` que T-3.1 debe caracterizar antes de la extraccion de T-3.2.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from gestor_luces.adapters.ui_webview.app_menu import AppMenu, AppMenuItem
from gestor_luces.main import _sync_native_menu, _to_webview_menus


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
    monkeypatch.setattr("gestor_luces.main.sys.platform", "linux")
    calls: list[bool] = []
    _sync_native_menu(SimpleNamespace(native=SimpleNamespace()), _menu_spec())
    assert calls == []


def test_sync_native_menu_skips_missing_or_disposed_native(monkeypatch) -> None:
    """`_sync_native_menu` retorna sin tocar nada si no hay ventana nativa valida."""
    monkeypatch.setattr("gestor_luces.main.sys.platform", "win32")

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
    monkeypatch.setattr("gestor_luces.main.sys.platform", "win32")

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
