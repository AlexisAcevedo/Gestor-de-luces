"""Pruebas de la vista de bandeja nativa de WinForms (`ContextMenuStrip` + `NotifyIcon`).

Las pruebas que necesitan .NET se saltan cuando pythonnet/WinForms no estan disponibles
(Linux, CI sin CLR), de modo que la suite sigue siendo portable. Ninguna prueba crea una
ventana visible ni llama a `Application.Run`: la vista solo se ejerce a traves del modelo
puro y de los objetos `ToolStripMenuItem` que produce el helper de construccion.
"""

from __future__ import annotations

from typing import Any

import pytest

from gestor_luces.adapters.tray import TrayMenuEntry, TrayPreset, build_tray_menu_spec
from gestor_luces.adapters.tray.menu_model import (
    ACTION_APPLY_PRESET,
    ACTION_CANCEL_SLEEP_TIMER,
    ACTION_QUIT,
    ACTION_SET_BRIGHTNESS,
    ACTION_TURN_OFF,
)
from gestor_luces.adapters.tray.tray_view import WINDOW_TOGGLE_ACTION, resolve_entry_action
from gestor_luces.adapters.tray.winforms_tray import (
    DARK_PALETTE,
    DEFAULT_PALETTE,
    LIGHT_PALETTE,
    THEME_PALETTES,
    _build_menu_items,
    _load_winforms,
    create_winforms_view,
    parse_hex_color,
    resolve_palette,
)

ARCHITECTURAL_STONE = "architectural-stone"
ATMOSPHERIC_DARK = "atmospheric-dark"


def _winforms() -> Any:
    """Resuelve pythonnet/WinForms o salta la prueba si no estan disponibles."""
    api = _load_winforms()
    if api is None:
        pytest.skip("pythonnet/WinForms is not available in this environment")
    return api


def _rgb(color: Any) -> tuple[int, int, int]:
    """Extrae el canal RGB de un `System.Drawing.Color`."""
    return (int(color.R), int(color.G), int(color.B))


def _dispose(items: list[Any]) -> None:
    """Libera los items creados por el helper (y sus submenus)."""
    for item in items:
        for child in getattr(item, "DropDownItems", []):
            image = getattr(child, "Image", None)
            if image is not None:
                image.Dispose()
        image = getattr(item, "Image", None)
        if image is not None:
            image.Dispose()
        item.Dispose()


def _spec(**overrides: Any) -> list[TrayMenuEntry]:
    params: dict[str, Any] = {
        "is_on": True,
        "brightness": 75,
        "presets": [TrayPreset(id="fav1", name="Cinema Mode", is_favorite=True)],
        "window_visible": True,
        "sleep_timer_active": True,
        "language": "es",
    }
    params.update(overrides)
    return build_tray_menu_spec(**params)


def _by_label(items: list[Any], label: str) -> Any:
    for item in items:
        if item.Text == label:
            return item
    raise AssertionError(f"item '{label}' not found in {[item.Text for item in items]}")


def test_palette_table_covers_both_themes_with_the_documented_colors() -> None:
    """Cada tema tiene paleta explicita y cualquier tema desconocido cae en la clara."""
    assert resolve_palette(ARCHITECTURAL_STONE) is LIGHT_PALETTE
    assert resolve_palette(ATMOSPHERIC_DARK) is DARK_PALETTE
    assert resolve_palette(" ARCHITECTURAL-STONE ") is LIGHT_PALETTE
    assert resolve_palette("no-such-theme") is LIGHT_PALETTE
    assert resolve_palette(None) is LIGHT_PALETTE
    assert DEFAULT_PALETTE is LIGHT_PALETTE

    assert LIGHT_PALETTE.background == "#F7F5F2"
    assert LIGHT_PALETTE.text == "#1C1C1F"
    assert LIGHT_PALETTE.disabled_text == "#8A8A8E"
    assert LIGHT_PALETTE.selection == "#E4DED6"
    assert DARK_PALETTE.background == "#1B1B1F"
    assert DARK_PALETTE.text == "#E6E6EA"
    assert DARK_PALETTE.disabled_text == "#7A7A82"
    assert DARK_PALETTE.selection == "#2A2A31"
    assert set(THEME_PALETTES) == {ARCHITECTURAL_STONE, ATMOSPHERIC_DARK}


def test_hex_colors_parse_to_rgb_channels() -> None:
    """La tabla de paleta se convierte a canales RGB sin depender de .NET."""
    assert parse_hex_color("#F7F5F2") == (0xF7, 0xF5, 0xF2)
    assert parse_hex_color("1B1B1F") == (0x1B, 0x1B, 0x1F)
    with pytest.raises(ValueError):
        parse_hex_color("#FFF")


def test_create_winforms_view_returns_none_when_winforms_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin CLR la vista devuelve None (nunca lanza) y la bandeja cae a pystray."""
    import gestor_luces.adapters.tray.winforms_tray as winforms_tray

    monkeypatch.setattr(winforms_tray, "_load_winforms", lambda: None)
    assert create_winforms_view(lambda action_id, payload: None) is None


def test_menu_items_map_the_model_with_the_dark_palette() -> None:
    """El arbol de items y sus colores siguen el modelo con la paleta oscura."""
    api = _winforms()
    dispatched: list[tuple[str, Any]] = []
    items = _build_menu_items(
        _spec(),
        DARK_PALETTE,
        lambda action_id, payload: dispatched.append((action_id, payload)),
        api=api,
    )
    try:
        assert [item.Text for item in items] == [
            "Apagar",
            "Ocultar ventana",
            "",
            "Brillo",
            "Escenas favoritas",
            "Cancelar temporizador",
            "",
            "Salir",
        ]
        background = parse_hex_color(DARK_PALETTE.background)
        text = parse_hex_color(DARK_PALETTE.text)
        selection = parse_hex_color(DARK_PALETTE.selection)

        power = _by_label(items, "Apagar")
        assert isinstance(power, api.forms.ToolStripMenuItem)
        assert _rgb(power.BackColor) == background
        assert _rgb(power.ForeColor) == text

        # El separador es el separador nativo, no un item de texto vacio.
        separators = [item for item in items if isinstance(item, api.forms.ToolStripSeparator)]
        assert len(separators) == 2

        brightness = _by_label(items, "Brillo")
        levels = list(brightness.DropDownItems)
        assert [level.Text for level in levels] == ["10%", "25%", "50%", "75%", "100%"]
        assert _rgb(brightness.DropDown.BackColor) == selection
        for level in levels:
            assert _rgb(level.BackColor) == selection
            assert _rgb(level.ForeColor) == text
        checked = [level for level in levels if level.Checked]
        assert [level.Text for level in checked] == ["75%"]
        # El check nativo tiene color fijo; el nivel activo se marca con un punto propio.
        assert checked[0].Image is not None
        assert checked[0].CheckOnClick is False
        assert all(level.Image is None for level in levels if not level.Checked)
    finally:
        _dispose(items)


def test_menu_items_use_the_light_palette_and_disabled_color() -> None:
    """La paleta clara pinta fondo, texto y texto deshabilitado del modelo."""
    api = _winforms()
    items = _build_menu_items(
        _spec(presets=[]),
        LIGHT_PALETTE,
        lambda action_id, payload: None,
        api=api,
    )
    try:
        background = parse_hex_color(LIGHT_PALETTE.background)
        text = parse_hex_color(LIGHT_PALETTE.text)
        disabled = parse_hex_color(LIGHT_PALETTE.disabled_text)

        quit_item = _by_label(items, "Salir")
        assert _rgb(quit_item.BackColor) == background
        assert _rgb(quit_item.ForeColor) == text

        presets = _by_label(items, "Escenas favoritas")
        placeholder = list(presets.DropDownItems)[0]
        assert placeholder.Text == "Sin escenas guardadas"
        assert placeholder.Enabled is False
        assert _rgb(placeholder.ForeColor) == disabled
    finally:
        _dispose(items)


def test_submenu_parents_expose_dropdown_items_without_click_hacks() -> None:
    """Brillo y Escenas favoritas son submenus reales; un clic en el padre no despacha."""
    api = _winforms()
    dispatched: list[tuple[str, Any]] = []
    spec = _spec()
    items = _build_menu_items(
        spec,
        DARK_PALETTE,
        lambda action_id, payload: dispatched.append((action_id, payload)),
        api=api,
    )

    def assert_same_tree(entries: list[TrayMenuEntry], built: list[Any]) -> None:
        assert len(entries) == len(built)
        for entry, item in zip(entries, built, strict=True):
            if entry.is_separator:
                assert isinstance(item, api.forms.ToolStripSeparator)
                continue
            assert item.Text == entry.label
            if entry.children:
                assert item.DropDownItems.Count == len(entry.children)
                assert_same_tree(list(entry.children), list(item.DropDownItems))
            else:
                assert item.DropDownItems.Count == 0

    try:
        assert_same_tree(spec, items)
        for label in ("Brillo", "Escenas favoritas"):
            parent = _by_label(items, label)
            assert isinstance(parent, api.forms.ToolStripMenuItem)
            entry = next(entry for entry in spec if entry.label == label)
            assert resolve_entry_action(entry) is None
            # El menu se despliega por `DropDownItems` (hover nativo), no por un clic.
            assert parent.DropDownItems.Count == len(entry.children)
            parent.PerformClick()
            assert parent.DropDown.Visible is False
        assert dispatched == []
    finally:
        _dispose(items)


def test_leaf_clicks_dispatch_their_action_and_payload() -> None:
    """Cada hoja entrega al despacho su `(action_id, payload)` exacto."""
    api = _winforms()
    dispatched: list[tuple[str, Any]] = []
    items = _build_menu_items(
        _spec(),
        DARK_PALETTE,
        lambda action_id, payload: dispatched.append((action_id, payload)),
        api=api,
    )
    try:
        _by_label(items, "Apagar").PerformClick()
        _by_label(items, "Salir").PerformClick()
        _by_label(items, "Cancelar temporizador").PerformClick()
        brightness = _by_label(items, "Brillo")
        next(level for level in brightness.DropDownItems if level.Text == "25%").PerformClick()
        presets = _by_label(items, "Escenas favoritas")
        next(level for level in presets.DropDownItems if level.Text == "Cinema Mode").PerformClick()
    finally:
        _dispose(items)

    assert dispatched == [
        (ACTION_TURN_OFF, None),
        (ACTION_QUIT, None),
        (ACTION_CANCEL_SLEEP_TIMER, None),
        (ACTION_SET_BRIGHTNESS, 25),
        (ACTION_APPLY_PRESET, "fav1"),
    ]


def test_default_window_entry_dispatches_the_window_toggle() -> None:
    """El item por defecto despacha `toggle_window` (un clic sobre el icono oculto abre)."""
    api = _winforms()
    dispatched: list[tuple[str, Any]] = []
    items = _build_menu_items(
        _spec(window_visible=False),
        LIGHT_PALETTE,
        lambda action_id, payload: dispatched.append((action_id, payload)),
        api=api,
    )
    try:
        window_item = _by_label(items, "Abrir consola")
        window_item.PerformClick()
    finally:
        _dispose(items)
    assert dispatched == [(WINDOW_TOGGLE_ACTION, None)]


def test_disabled_entries_never_dispatch() -> None:
    """Un item deshabilitado no ejecuta ninguna accion aunque se active por codigo."""
    api = _winforms()
    dispatched: list[tuple[str, Any]] = []
    spec = _spec(presets=[])
    items = _build_menu_items(
        spec,
        DARK_PALETTE,
        lambda action_id, payload: dispatched.append((action_id, payload)),
        api=api,
    )
    try:
        presets = _by_label(items, "Escenas favoritas")
        placeholder = list(presets.DropDownItems)[0]
        assert placeholder.Enabled is False
        placeholder.PerformClick()
    finally:
        _dispose(items)
    assert dispatched == []


def test_icon_is_cached_by_color_and_replaced_handles_are_destroyed() -> None:
    """Un refresco con el mismo color no asigna icono; el HICON reemplazado se libera."""
    _winforms()
    destroyed: list[int] = []
    view = create_winforms_view(lambda action_id, payload: None, destroy_icon=destroyed.append)
    assert view is not None

    first = view._icon_for((10, 20, 30))
    assert view._icon_for((10, 20, 30)) is first
    assert destroyed == []

    second = view._icon_for((40, 50, 60))
    assert second is not first
    assert len(destroyed) == 1
    assert destroyed[0] > 0

    # La ruta de limpieza libera el icono vigente y su HICON.
    view._dispose_native()
    assert len(destroyed) == 2
    assert destroyed[1] > 0
    assert destroyed[0] != destroyed[1]


def test_created_view_caches_state_without_touching_winforms() -> None:
    """Antes de `run` la vista solo cachea: no crea `Form`, `NotifyIcon` ni menu."""
    api = _winforms()
    view = create_winforms_view(lambda action_id, payload: None)
    assert view is not None
    spec = _spec()
    view.apply(spec, "WiZ Lighting - On 75%", (0x10, 0x20, 0x30), ATMOSPHERIC_DARK)
    # Ningun objeto nativo se crea fuera del hilo de bombeo (no hay ventana ni icono).
    assert getattr(view, "_form", "missing") is None
    assert getattr(view, "_notify", "missing") is None
    view.stop()
    assert api is not None
