"""Pruebas de la vista de bandeja nativa de WinForms (`ContextMenuStrip` + `NotifyIcon`).

Las pruebas que necesitan .NET se saltan cuando pythonnet/WinForms no estan disponibles
(Linux, CI sin CLR), de modo que la suite sigue siendo portable. Ninguna prueba crea una
ventana visible ni llama a `Application.Run`: la vista solo se ejerce a traves del modelo
puro, de los objetos `ToolStripMenuItem` que produce el helper de construccion y de las
funciones puras de acabado (firmas, geometria de la region y estilos de pintado).
"""

from __future__ import annotations

import ctypes
import logging
import types
from typing import Any

import pytest

from gestor_luces.adapters.platform.windows.window_chrome import (
    DWMWA_WINDOW_CORNER_PREFERENCE,
    DWMWCP_ROUND,
    _apply_corner_preference,
)
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
    MENU_ITEM_PADDING_VERTICAL,
    THEME_PALETTES,
    WinFormsTrayView,
    _build_menu_items,
    _load_winforms,
    create_winforms_view,
    item_paint_style,
    menu_region_geometry,
    menu_signature,
    paint_menu_item,
    paint_menu_separator,
    parse_hex_color,
    resolve_palette,
    separator_paint_style,
    state_signature,
)

ARCHITECTURAL_STONE = "architectural-stone"
ATMOSPHERIC_DARK = "atmospheric-dark"
TRAY_VIEW_LOGGER = "gestor_luces.adapters.tray.tray_view"


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
        for child in list(getattr(item, "DropDownItems", []) or []):
            child.Dispose()
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
    assert LIGHT_PALETTE.separator == "#D9D1C6"
    assert DARK_PALETTE.background == "#1B1B1F"
    assert DARK_PALETTE.text == "#E6E6EA"
    assert DARK_PALETTE.disabled_text == "#7A7A82"
    assert DARK_PALETTE.selection == "#2A2A31"
    assert DARK_PALETTE.separator == "#3A3A42"
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

        power = _by_label(items, "Apagar")
        assert isinstance(power, api.forms.ToolStripMenuItem)
        assert _rgb(power.BackColor) == background
        assert _rgb(power.ForeColor) == text
        # Filas altas: el padding vertical duplica el valor documentado (~28 px).
        assert power.Padding.Vertical == 2 * MENU_ITEM_PADDING_VERTICAL

        # El separador es el separador nativo, no un item de texto vacio.
        separators = [item for item in items if isinstance(item, api.forms.ToolStripSeparator)]
        assert len(separators) == 2

        brightness = _by_label(items, "Brillo")
        levels = list(brightness.DropDownItems)
        assert [level.Text for level in levels] == ["10%", "25%", "50%", "75%", "100%"]
        assert _rgb(brightness.DropDown.BackColor) == background
        for level in levels:
            assert _rgb(level.BackColor) == background
            assert _rgb(level.ForeColor) == text
        checked = [level for level in levels if level.Checked]
        assert [level.Text for level in checked] == ["75%"]
        # El nivel activo ya no depende del glifo nativo ni de una imagen: la vista dibuja
        # el punto con el color del texto de la paleta (visible en ambos temas).
        assert checked[0].CheckOnClick is False
        assert _rgb(checked[0].ForeColor) == text
        assert all(level.Image is None for level in levels)
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


# --- Firmas separadas: menu vs estado (T-3.9) ------------------------------------------


def test_menu_signature_covers_structure_and_theme_only() -> None:
    """La firma del menu no cambia con el tooltip ni con el tinte del icono."""
    spec = _spec()
    assert menu_signature(spec, ATMOSPHERIC_DARK) == (tuple(spec), ATMOSPHERIC_DARK)
    assert menu_signature(spec, None) == (tuple(spec), "")

    base = state_signature(spec, "WiZ Lighting - On 75%", (10, 20, 30), ATMOSPHERIC_DARK)
    retitled = state_signature(spec, "WiZ Lighting - Off", (10, 20, 30), ATMOSPHERIC_DARK)
    recolored = state_signature(spec, "WiZ Lighting - On 75%", (40, 50, 60), ATMOSPHERIC_DARK)
    assert base[0] == retitled[0] == recolored[0] == menu_signature(spec, ATMOSPHERIC_DARK)
    assert base != retitled
    assert base != recolored

    # Una estructura distinta o un tema distinto si cambian la firma del menu.
    other_spec = _spec(is_on=False)
    assert state_signature(other_spec, "t", (1, 2, 3), ATMOSPHERIC_DARK)[0] != base[0]
    assert state_signature(spec, "t", (1, 2, 3), ARCHITECTURAL_STONE)[0] != base[0]


class _FakeNotifyIcon:
    """Doble del `NotifyIcon` nativo: registra que propiedades recibieron valor."""

    def __init__(self) -> None:
        self.Icon: Any = None
        self.Text = ""
        self.Visible = False
        self.ContextMenuStrip: Any = None


class _FakeMenu:
    """Doble del `ContextMenuStrip`: solo lo que la vista consulta y libera."""

    def __init__(self, visible: bool = False) -> None:
        self.Visible = visible
        self.disposed = False

    def Dispose(self) -> None:
        self.disposed = True


class _ViewWithoutClr(WinFormsTrayView):
    """Vista con el CLR reemplazado por dobles contables (no necesita WinForms)."""

    def __init__(self) -> None:
        super().__init__(lambda action_id, payload: None, api=types.SimpleNamespace())
        self.built: list[list[TrayMenuEntry]] = []
        self.notify = _FakeNotifyIcon()
        self._notify = self.notify

    def _build_menu(self, spec: Any, palette: Any) -> _FakeMenu:
        self.built.append(list(spec))
        return _FakeMenu()

    def _icon_for(self, rgb: tuple[int, int, int]) -> str:
        return f"icon-rgb{rgb}"


def _rebuilt_logs(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Lineas de log de la vista de bandeja, para contar rebuilds exactamente."""
    return [record.getMessage() for record in caplog.records if record.name == TRAY_VIEW_LOGGER]


def test_icon_and_title_changes_never_rebuild_the_menu(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regresion del log con cinco rebuilds: rgb/tooltip solo tocan el icono."""
    caplog.set_level(logging.INFO, logger=TRAY_VIEW_LOGGER)
    view = _ViewWithoutClr()
    spec = _spec()

    view._apply_native((list(spec), "WiZ Lighting - On 75%", (10, 20, 30), ATMOSPHERIC_DARK))
    first_menu = view.notify.ContextMenuStrip
    assert len(view.built) == 1
    assert view.notify.Icon == "icon-rgb(10, 20, 30)"
    assert view.notify.Text == "WiZ Lighting - On 75%"
    assert sum("Tray menu rebuilt" in line for line in _rebuilt_logs(caplog)) == 1

    # Mismo spec y tema, otro color de icono: ni rebuild ni linea de log nueva.
    view._apply_native((list(spec), "WiZ Lighting - On 75%", (40, 50, 60), ATMOSPHERIC_DARK))
    assert len(view.built) == 1
    assert view.notify.ContextMenuStrip is first_menu
    assert view.notify.Icon == "icon-rgb(40, 50, 60)"
    assert sum("Tray menu rebuilt" in line for line in _rebuilt_logs(caplog)) == 1

    # Mismo spec y tema, otro tooltip: tampoco reconstruye el menu.
    view._apply_native((list(spec), "WiZ Lighting - Off", (40, 50, 60), ATMOSPHERIC_DARK))
    assert len(view.built) == 1
    assert view.notify.ContextMenuStrip is first_menu
    assert view.notify.Text == "WiZ Lighting - Off"
    assert sum("Tray menu rebuilt" in line for line in _rebuilt_logs(caplog)) == 1

    # Otra estructura: un unico rebuild, una unica linea y el menu anterior liberado.
    view._apply_native(
        (list(_spec(is_on=False)), "WiZ Lighting - Off", (40, 50, 60), ATMOSPHERIC_DARK)
    )
    assert len(view.built) == 2
    assert view.notify.ContextMenuStrip is not first_menu
    assert first_menu.disposed is True
    assert sum("Tray menu rebuilt" in line for line in _rebuilt_logs(caplog)) == 2

    # Otro tema con la misma estructura: la paleta obliga a reconstruir.
    view._apply_native(
        (list(_spec(is_on=False)), "WiZ Lighting - Off", (40, 50, 60), ARCHITECTURAL_STONE)
    )
    assert len(view.built) == 3
    assert sum("Tray menu rebuilt" in line for line in _rebuilt_logs(caplog)) == 3


def test_only_the_rebuild_is_deferred_while_a_menu_is_displayed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Con el menu desplegado el rebuild espera; tooltip e icono se aplican igual."""
    caplog.set_level(logging.INFO, logger=TRAY_VIEW_LOGGER)
    view = _ViewWithoutClr()
    view._apply_native((list(_spec()), "t-on", (1, 2, 3), ARCHITECTURAL_STONE))
    displayed_menu = view.notify.ContextMenuStrip
    assert isinstance(displayed_menu, _FakeMenu)
    displayed_menu.Visible = True

    pending = (list(_spec(is_on=False)), "t-off", (4, 5, 6), ARCHITECTURAL_STONE)
    view._apply_native(pending)
    assert len(view.built) == 1, "un menu desplegado nunca se reemplaza"
    assert view.notify.ContextMenuStrip is displayed_menu
    # Tooltip y tinte no se difieren: no necesitan reemplazar nada.
    assert view.notify.Text == "t-off"
    assert view.notify.Icon == "icon-rgb(4, 5, 6)"
    deferred = [line for line in _rebuilt_logs(caplog) if "deferred" in line]
    assert len(deferred) == 1

    # El mismo estado pendiente no vuelve a loguear mientras el menu siga abierto.
    view._apply_native(pending)
    deferred = [line for line in _rebuilt_logs(caplog) if "deferred" in line]
    assert len(deferred) == 1

    # Al cerrarse el menu, el proximo refresco reintenta el rebuild una sola vez.
    displayed_menu.Visible = False
    view._apply_native(pending)
    assert len(view.built) == 2
    assert view.notify.ContextMenuStrip is not displayed_menu
    assert sum("Tray menu rebuilt" in line for line in _rebuilt_logs(caplog)) == 2


# --- Esquinas de DWM y recorte de la ventana del menu (T-3.9) --------------------------


class _FakeHandle:
    """Handle nativo minimo con la conversion que usa la capa Windows."""

    def __init__(self, value: int) -> None:
        self._value = value

    def ToInt64(self) -> int:
        return self._value


class _FakeControl:
    def __init__(self, hwnd: int) -> None:
        self.Handle = _FakeHandle(hwnd)


def _read_int(pointer: Any) -> int:
    """Lee el `c_int` que la capa Windows pasa por `byref`."""
    value = getattr(pointer, "_obj", None)
    if value is not None:
        return int(value.value)
    return int(ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int)).contents.value)


class _FakeDwmApi:
    def __init__(self, result: int = 0) -> None:
        self.result = result
        self.calls: list[tuple[int, int, int, int]] = []

    def DwmSetWindowAttribute(self, hwnd: int, attribute: int, value: Any, size: int) -> int:
        self.calls.append((int(hwnd), int(attribute), _read_int(value), int(size)))
        return self.result


def test_corner_preference_asks_dwm_for_attribute_33_and_round() -> None:
    """Las esquinas se piden con DWMWA_WINDOW_CORNER_PREFERENCE = 33 y DWMWCP_ROUND = 2."""
    fake = _FakeDwmApi()
    control = _FakeControl(0x1234)

    assert DWMWA_WINDOW_CORNER_PREFERENCE == 33
    assert DWMWCP_ROUND == 2
    assert _apply_corner_preference(control, platform="win32", dwmapi=fake) is True
    assert fake.calls == [(0x1234, 33, 2, ctypes.sizeof(ctypes.c_int))]


def test_corner_preference_degrades_without_dwm_or_handle() -> None:
    """Sin Win32, sin handle o con un DWM incompleto no hay excepcion ni llamada."""
    control = _FakeControl(0x1234)
    fake = _FakeDwmApi()

    assert _apply_corner_preference(control, platform="linux", dwmapi=fake) is False
    assert fake.calls == []

    # `dwmapi` sin la funcion esperada (doble incompleto).
    assert _apply_corner_preference(control, platform="win32", dwmapi=object()) is False

    # Sin handle nativo no hay ventana que redondear.
    assert _apply_corner_preference(object(), platform="win32", dwmapi=fake) is False
    assert fake.calls == []

    class _ExplodingDwm:
        def DwmSetWindowAttribute(self, *_args: Any) -> int:
            raise OSError("dwm unavailable")

    assert _apply_corner_preference(control, platform="win32", dwmapi=_ExplodingDwm()) is False

    # `dwmapi=None` cae a `ctypes.windll.dwmapi`: en un entorno sin Win32 solo degrada.
    assert isinstance(_apply_corner_preference(control, platform="win32", dwmapi=None), bool)


def test_menu_region_geometry_insets_and_clamps_the_corner_radius() -> None:
    """La region recorta 1 px (quita el borde del renderer) y escala el radio por DPI."""
    assert menu_region_geometry(170, 184) == (1, 1, 169, 183, 8)
    assert menu_region_geometry(170, 184, scale=1.5)[4] == 12
    # Un menu demasiado chico no genera region (no se crea una region invalida).
    assert menu_region_geometry(4, 4) is None
    # El radio nunca supera la mitad del lado menor.
    geometry = menu_region_geometry(40, 20)
    assert geometry is not None
    assert geometry[4] == 8


# --- Estilos de pintado por fila (T-3.9) -----------------------------------------------


def test_item_paint_styles_come_from_the_palette() -> None:
    """Normal, hover, deshabilitado, marcado y separador usan los colores de la paleta."""
    for palette in (LIGHT_PALETTE, DARK_PALETTE):
        normal = item_paint_style(palette, hovered=False)
        assert normal.background == palette.background
        assert normal.text == palette.text
        assert normal.mark == palette.text

        hovered = item_paint_style(palette, hovered=True)
        assert hovered.background == palette.selection
        assert hovered.text == palette.text

        disabled = item_paint_style(palette, hovered=True, enabled=False)
        assert disabled.background == palette.selection
        assert disabled.text == palette.disabled_text

        separator = separator_paint_style(palette)
        assert separator.background == palette.background
        assert separator.mark == palette.separator

        assert palette.separator != palette.background


class _RecordingGraphics:
    """Superficie de dibujo que registra el color de cada operacion."""

    def __init__(self) -> None:
        self.ops: list[tuple[Any, ...]] = []

    def FillRectangle(self, brush: Any, rectangle: Any) -> None:
        self.ops.append(("fill", brush.color, tuple(rectangle)))

    def FillEllipse(self, brush: Any, _x: int, _y: int, _width: int, _height: int) -> None:
        self.ops.append(("dot", brush.color))

    def DrawString(self, text: str, _font: Any, brush: Any, _rect: Any, _fmt: Any) -> None:
        self.ops.append(("text", brush.color, text))

    def DrawLine(self, pen: Any, _x1: int, _y1: int, _x2: int, _y2: int) -> None:
        self.ops.append(("line", pen.color))


class _FakeBrush:
    def __init__(self, color: Any) -> None:
        self.color = color

    def Dispose(self) -> None:
        return None


class _FakePen(_FakeBrush):
    def __init__(self, color: Any, width: float = 1.0) -> None:
        super().__init__(color)
        self.width = width


class _FakeStringFormat:
    def __init__(self) -> None:
        self.LineAlignment: Any = None
        self.FormatFlags: Any = None

    def Dispose(self) -> None:
        return None


class _FakeDrawingModule:
    """Minimo de `System.Drawing` que consume el pintado de filas."""

    class Color:
        @staticmethod
        def FromArgb(red: int, green: int, blue: int) -> tuple[int, int, int]:
            return (int(red), int(green), int(blue))

    class StringAlignment:
        Center = "Center"

    class StringFormatFlags:
        NoWrap = "NoWrap"

    def SolidBrush(self, color: Any) -> _FakeBrush:
        return _FakeBrush(color)

    def Pen(self, color: Any, width: float = 1.0) -> _FakePen:
        return _FakePen(color, width)

    def Rectangle(self, x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
        return (x, y, width, height)

    def RectangleF(self, x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
        return (x, y, width, height)

    def StringFormat(self) -> _FakeStringFormat:
        return _FakeStringFormat()


FAKE_API = types.SimpleNamespace(drawing=_FakeDrawingModule())


def test_paint_menu_item_uses_palette_colors_for_normal_hover_and_checked() -> None:
    """El pintor de filas usa fondo, hover, texto y marca de la paleta activa."""
    normal = _RecordingGraphics()
    paint_menu_item(
        normal,
        palette=DARK_PALETTE,
        api=FAKE_API,
        text="Apagar",
        font=object(),
        width=169,
        height=28,
        hovered=False,
    )
    assert normal.ops[0] == (
        "fill",
        parse_hex_color(DARK_PALETTE.background),
        (0, 0, 169, 28),
    )
    assert ("text", parse_hex_color(DARK_PALETTE.text), "Apagar") in normal.ops
    assert all(op[0] != "dot" for op in normal.ops)

    hovered = _RecordingGraphics()
    style = paint_menu_item(
        hovered,
        palette=DARK_PALETTE,
        api=FAKE_API,
        text="Brillo",
        font=object(),
        width=169,
        height=28,
        hovered=True,
    )
    assert style.background == DARK_PALETTE.selection
    assert hovered.ops[0] == (
        "fill",
        parse_hex_color(DARK_PALETTE.selection),
        (0, 0, 169, 28),
    )

    checked = _RecordingGraphics()
    paint_menu_item(
        checked,
        palette=DARK_PALETTE,
        api=FAKE_API,
        text="75%",
        font=object(),
        width=169,
        height=28,
        hovered=True,
        checked=True,
    )
    assert ("dot", parse_hex_color(DARK_PALETTE.text)) in checked.ops

    disabled = _RecordingGraphics()
    paint_menu_item(
        disabled,
        palette=LIGHT_PALETTE,
        api=FAKE_API,
        text="Sin escenas guardadas",
        font=object(),
        width=169,
        height=28,
        hovered=False,
        enabled=False,
    )
    assert (
        "text",
        parse_hex_color(LIGHT_PALETTE.disabled_text),
        "Sin escenas guardadas",
    ) in disabled.ops

    submenu = _RecordingGraphics()
    paint_menu_item(
        submenu,
        palette=LIGHT_PALETTE,
        api=FAKE_API,
        text="Escenas favoritas",
        font=object(),
        width=169,
        height=28,
        hovered=False,
        has_children=True,
    )
    assert [op for op in submenu.ops if op[0] == "line"] == [
        ("line", parse_hex_color(LIGHT_PALETTE.text)),
        ("line", parse_hex_color(LIGHT_PALETTE.text)),
    ]


def test_paint_menu_separator_uses_the_separator_color() -> None:
    """El separador no usa el color fijo del sistema: fondo del menu y linea propia."""
    for palette in (LIGHT_PALETTE, DARK_PALETTE):
        graphics = _RecordingGraphics()
        style = paint_menu_separator(
            graphics,
            palette=palette,
            api=FAKE_API,
            width=166,
            height=6,
        )
        assert style.mark == palette.separator
        assert graphics.ops[0] == (
            "fill",
            parse_hex_color(palette.background),
            (0, 0, 166, 6),
        )
        assert graphics.ops[1][0] == "line"
        assert graphics.ops[1][1] == parse_hex_color(palette.separator)
