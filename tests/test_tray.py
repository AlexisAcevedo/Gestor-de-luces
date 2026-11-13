"""Pruebas del adaptador de bandeja del sistema.

Cubre tres niveles:
1. Modelo puro (`menu_model`) y generador de iconos, sin hilos ni toolkits.
2. `TrayController` contra una vista falsa, que registra cada estado aplicado.
3. Vistas concretas: la de `pystray` (respaldo, con su menu nativo real) y el despacho
   de acciones que ambas comparten.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from gestor_luces.adapters.storage.json_repositories import (
    JsonBulbRepository,
    JsonSceneRepository,
)
from gestor_luces.adapters.tray import (
    TrayController,
    TrayMenuEntry,
    TrayPreset,
    build_tray_menu_spec,
    build_tray_title,
    render_icon_image,
    resolve_entry_action,
    resolve_icon_rgb,
)
from gestor_luces.adapters.tray.menu_model import (
    ACTION_APPLY_PRESET,
    ACTION_CANCEL_SLEEP_TIMER,
    ACTION_HIDE_WINDOW,
    ACTION_QUIT,
    ACTION_SET_BRIGHTNESS,
    ACTION_SHOW_WINDOW,
    ACTION_TURN_OFF,
    ACTION_TURN_ON,
    FALLBACK_PRESET_LIMIT,
    OFF_ICON_RGB,
    SCENE_ICON_RGB,
    closest_brightness_level,
    select_tray_presets,
)
from gestor_luces.adapters.tray.pystray_tray import (
    PystrayTrayView,
    _owner_popup_icon_class,
    create_pystray_view,
)
from gestor_luces.adapters.tray.tray_icon import REFRESH_THREAD_NAME
from gestor_luces.adapters.tray.tray_view import WINDOW_TOGGLE_ACTION, TrayView
from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from tests.waits import POLL_SECONDS


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Espera a que el hilo de refresco de la bandeja aplique el estado esperado.

    Las acciones del menu no tocan el estado nativo: encolan un refresco, y el estado
    (titulo y modelo del menu) lo aplica el hilo de refresco del controlador.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(POLL_SECONDS)
    raise AssertionError("tray refresh did not apply the expected state in time")


class FakeTrayView:
    """Vista de prueba que registra cada `apply` sin abrir ningun toolkit grafico."""

    def __init__(self) -> None:
        self.applies: list[tuple[list[TrayMenuEntry], str, tuple[int, int, int], str]] = []
        self.applied_threads: list[str] = []
        self.run_called = False
        self.stop_called = False

    def run(self) -> None:
        self.run_called = True

    def stop(self) -> None:
        self.stop_called = True

    def apply(
        self,
        spec: list[TrayMenuEntry],
        title: str,
        rgb: tuple[int, int, int],
        theme: str,
    ) -> None:
        self.applies.append((list(spec), title, tuple(rgb), theme))
        self.applied_threads.append(threading.current_thread().name)

    @property
    def last(self) -> tuple[list[TrayMenuEntry], str, tuple[int, int, int], str]:
        assert self.applies, "the view never received a state"
        return self.applies[-1]

    @property
    def title(self) -> str:
        return self.last[1]

    @property
    def spec(self) -> list[TrayMenuEntry]:
        return self.last[0]

    @property
    def theme(self) -> str:
        return self.last[3]


class FakeTrayIcon:
    """Doble de prueba de `pystray.Icon` para inspeccionar la vista de respaldo.

    `run` bloquea hasta `stop`, igual que el bombeo real: asi la vista conserva el icono
    vigente mientras la prueba interactua con el menu.
    """

    def __init__(self, name: str, image: Any, title: str, menu: Any) -> None:
        self.name = name
        self.icon = image
        self.title = title
        self.menu = menu
        self.run_called = False
        self.stop_called = False
        self.update_menu_count = 0
        self.update_menu_threads: list[str] = []
        self._stopped = threading.Event()

    def run(self) -> None:
        self.run_called = True
        self._stopped.wait(timeout=10)

    def stop(self) -> None:
        self.stop_called = True
        self._stopped.set()

    def update_menu(self) -> None:
        self.update_menu_count += 1
        self.update_menu_threads.append(threading.current_thread().name)


def _find_entry_by_label(entries: list[TrayMenuEntry], label: str) -> TrayMenuEntry:
    """Busca una entrada de primer nivel por su etiqueta exacta."""
    for entry in entries:
        if entry.label == label:
            return entry
    raise AssertionError(f"Menu entry '{label}' not found in {[e.label for e in entries]}")


def test_closest_brightness_level_and_preset_selection() -> None:
    """Verifica el redondeo al escalon de brillo mas cercano y la prioridad de favoritos."""
    assert closest_brightness_level(10) == 10
    assert closest_brightness_level(17) == 10
    assert closest_brightness_level(18) == 25
    assert closest_brightness_level(48) == 50
    assert closest_brightness_level(88) == 100

    # Sin favoritos marcados, se ofrecen hasta FALLBACK_PRESET_LIMIT presets de respaldo
    many_non_favorites = [
        TrayPreset(id=f"p{idx}", name=f"Preset {idx}", is_favorite=False) for idx in range(12)
    ]
    fallback = select_tray_presets(many_non_favorites)
    assert len(fallback) == FALLBACK_PRESET_LIMIT
    assert [p.id for p in fallback] == [f"p{idx}" for idx in range(FALLBACK_PRESET_LIMIT)]

    # En cuanto existe al menos un favorito, el submenu filtra exclusivamente favoritos
    with_favorites = [
        TrayPreset(id="p1", name="Warm Desk", is_favorite=False),
        TrayPreset(id="p2", name="Studio Key", is_favorite=True),
        TrayPreset(id="p3", name="Night Coding", is_favorite=True),
    ]
    selected = select_tray_presets(with_favorites)
    assert [p.id for p in selected] == ["p2", "p3"]


def test_build_tray_menu_spec_reflects_visibility_power_and_sleep_timer() -> None:
    """Comprueba que la especificacion del menu refleje cada combinacion de estado."""
    spec_hidden_off = build_tray_menu_spec(
        is_on=False,
        brightness=48,
        presets=[],
        window_visible=False,
        sleep_timer_active=False,
    )
    assert spec_hidden_off[1].label == "Open console"
    assert spec_hidden_off[1].action_id == ACTION_SHOW_WINDOW
    assert spec_hidden_off[1].is_default is True

    power_entry = _find_entry_by_label(spec_hidden_off, "Turn on")
    assert power_entry.action_id == ACTION_TURN_ON

    brightness_menu = _find_entry_by_label(spec_hidden_off, "Brightness")
    checked_levels = [c.payload for c in brightness_menu.children if c.checked]
    assert checked_levels == [50]

    presets_menu = _find_entry_by_label(spec_hidden_off, "Favorite presets")
    assert len(presets_menu.children) == 1
    assert presets_menu.children[0].label == "No saved presets"
    assert presets_menu.children[0].enabled is False
    assert all(e.action_id != ACTION_CANCEL_SLEEP_TIMER for e in spec_hidden_off)

    # Con ventana visible, foco encendido y temporizador activo
    spec_visible_on = build_tray_menu_spec(
        is_on=True,
        brightness=75,
        presets=[TrayPreset(id="fav1", name="Cinema Mode", is_favorite=True)],
        window_visible=True,
        sleep_timer_active=True,
    )
    assert spec_visible_on[1].label == "Hide window"
    assert spec_visible_on[1].action_id == ACTION_HIDE_WINDOW
    assert _find_entry_by_label(spec_visible_on, "Turn off").action_id == ACTION_TURN_OFF
    assert _find_entry_by_label(spec_visible_on, "Cancel sleep timer").action_id == (
        ACTION_CANCEL_SLEEP_TIMER
    )
    assert build_tray_title(True, 75) == "WiZ Lighting - On 75%"
    assert build_tray_title(False, 75) == "WiZ Lighting - Off"


def test_resolve_entry_action_maps_defaults_to_the_window_toggle() -> None:
    """El item por defecto (mostrar/ocultar ventana) despacha la accion sintetica."""
    spec = build_tray_menu_spec(
        is_on=True,
        brightness=100,
        presets=[],
        window_visible=False,
        sleep_timer_active=False,
    )
    show_entry = _find_entry_by_label(spec, "Open console")
    assert resolve_entry_action(show_entry) == (WINDOW_TOGGLE_ACTION, None)

    # El mismo item deja de despachar el toggle cuando no es el item por defecto.
    not_default = TrayMenuEntry(label="Open console", action_id=ACTION_SHOW_WINDOW)
    assert resolve_entry_action(not_default) == (ACTION_SHOW_WINDOW, None)

    # Un padre de submenu y un separador no despachan nada por si mismos.
    parent = _find_entry_by_label(spec, "Brightness")
    assert resolve_entry_action(parent) is None
    assert resolve_entry_action(TrayMenuEntry(is_separator=True)) is None

    # Las hojas de brillo llevan su nivel como payload.
    level = next(child for child in parent.children if child.payload == 50)
    assert resolve_entry_action(level) == (ACTION_SET_BRIGHTNESS, 50)


def test_resolve_icon_rgb_and_render_icon_image() -> None:
    """Verifica el calculo del color del icono por modo y la generacion RGBA 64x64."""
    assert (
        resolve_icon_rgb(is_on=False, mode="rgb", color=[255, 0, 0], temperature=None)
        == OFF_ICON_RGB
    )
    assert resolve_icon_rgb(is_on=True, mode="rgb", color=[12, 200, 95], temperature=None) == (
        12,
        200,
        95,
    )
    assert (
        resolve_icon_rgb(is_on=True, mode="scene", color=None, temperature=None) == SCENE_ICON_RGB
    )

    warm_rgb = resolve_icon_rgb(is_on=True, mode="temperature", color=None, temperature=2200)
    cool_rgb = resolve_icon_rgb(is_on=True, mode="temperature", color=None, temperature=6500)
    assert warm_rgb == (255, 180, 107)
    assert cool_rgb == (214, 232, 255)

    assert render_icon_image((20, 180, 240)) is not None
    img = render_icon_image((20, 180, 240))
    assert img.mode == "RGBA"
    assert img.size == (64, 64)
    center_pixel = img.getpixel((32, 32))
    assert center_pixel[:3] == (20, 180, 240)
    assert center_pixel[3] == 255
    corner_pixel = img.getpixel((0, 0))
    assert corner_pixel[3] == 0


class FakeTrayActions:
    """Estado luminico falso: evita bridge, UDP y relojes en las pruebas de menu."""

    def __init__(self) -> None:
        self.snapshot: dict[str, Any] = {
            "is_on": False,
            "brightness": 100,
            "language": "en",
            "mode": None,
            "color": None,
            "temperature": None,
            "presets": [],
            "sleep_timer_active": False,
            "theme": "architectural-stone",
        }
        self.power_calls: list[bool] = []
        self.brightness_calls: list[int] = []
        self.preset_calls: list[str] = []
        self.cancel_calls = 0

    def set_power(self, is_on: bool) -> dict[str, Any]:
        self.power_calls.append(is_on)
        return {"ok": True}

    def set_brightness(self, brightness: int) -> dict[str, Any]:
        self.brightness_calls.append(brightness)
        return {"ok": True}

    def apply_custom_scene(self, scene_id: str) -> dict[str, Any]:
        self.preset_calls.append(scene_id)
        return {"ok": True}

    def cancel_sleep_timer(self) -> dict[str, Any]:
        self.cancel_calls += 1
        return {"ok": True}

    def get_tray_snapshot(self) -> dict[str, Any]:
        return dict(self.snapshot)


class _TrayHarness:
    """Controlador ya arrancado con una vista falsa y contadores de acciones de ventana."""

    def __init__(self, *, poll_interval: float = 0.0) -> None:
        self.actions = FakeTrayActions()
        self.actions.snapshot["presets"] = [
            {"id": "p1", "name": "Warm Desk", "is_favorite": True},
        ]
        self.views: list[FakeTrayView] = []
        self.shown = 0
        self.hidden = 0
        self.quits = 0

        def factory(_dispatch: Callable[[str, Any], None]) -> TrayView:
            view = FakeTrayView()
            self.views.append(view)
            return view

        self.tray = TrayController(
            self.actions,
            show_window=self._on_show,
            hide_window=self._on_hide,
            quit_app=self._on_quit,
            is_window_visible=lambda: True,
            view_factory=factory,
            executor=lambda task: task(),
            poll_interval=poll_interval,
        )

    def _on_show(self) -> None:
        self.shown += 1

    def _on_hide(self) -> None:
        self.hidden += 1

    def _on_quit(self) -> None:
        self.quits += 1

    def __enter__(self) -> _TrayHarness:
        self.tray.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.tray.stop()

    @property
    def view(self) -> FakeTrayView:
        return self.views[0]


async def test_tray_controller_dispatches_all_actions_against_bridge_and_udp(
    tmp_path: Path,
) -> None:
    """Prueba todas las acciones del controlador de bandeja contra WebviewBridge y UDP."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(
            controller=controller,
            bulb_repository=JsonBulbRepository(data_dir=tmp_path),
            scene_repository=JsonSceneRepository(data_dir=tmp_path),
        )
        bridge = WebviewBridge(service=service)

        views: list[FakeTrayView] = []
        window_visible = True
        show_count = 0
        hide_count = 0
        quit_count = 0
        ui_notifications = 0

        def view_factory(_dispatch: Callable[[str, Any], None]) -> TrayView:
            view = FakeTrayView()
            views.append(view)
            return view

        def on_show() -> None:
            nonlocal window_visible, show_count
            window_visible = True
            show_count += 1

        def on_hide() -> None:
            nonlocal window_visible, hide_count
            window_visible = False
            hide_count += 1

        def on_quit() -> None:
            nonlocal quit_count
            quit_count += 1

        def on_notify_ui() -> None:
            nonlocal ui_notifications
            ui_notifications += 1

        tray = TrayController(
            bridge,
            show_window=on_show,
            hide_window=on_hide,
            quit_app=on_quit,
            is_window_visible=lambda: window_visible,
            notify_ui=on_notify_ui,
            view_factory=view_factory,
            executor=lambda task: task(),
            poll_interval=0.05,
        )
        bridge.set_state_change_listener(tray.request_refresh)

        try:
            await asyncio.to_thread(bridge.get_initial_state)

            # Creamos dos presets y marcamos el segundo como favorito para la bandeja
            await asyncio.to_thread(bridge.set_color, 255, 40, 100, 80)
            await asyncio.to_thread(bridge.save_custom_scene, "Crimson Pulse")
            await asyncio.to_thread(bridge.set_color, 10, 210, 140, 65)
            scenes_env = await asyncio.to_thread(bridge.save_custom_scene, "Mint Focus")
            fav_id = next(s["id"] for s in scenes_env["custom_scenes"] if s["name"] == "Mint Focus")
            await asyncio.to_thread(bridge.set_custom_scene_favorite, fav_id, True)

            await asyncio.to_thread(tray.start)
            assert len(views) == 1
            view = views[0]
            assert view.run_called is True
            assert view.title == "WiZ Lighting - On 65%"
            # El tema activo de la app viaja a la vista para que el menu use su paleta.
            assert view.theme == "architectural-stone"

            # El submenu de presets favoritos solo expone el preset marcado como favorito
            presets_menu = _find_entry_by_label(tray.spec, "Favorite presets")
            assert [c.label for c in presets_menu.children] == ["Mint Focus"]

            # 1. Apagar y volver a encender desde el menu de bandeja
            await asyncio.to_thread(tray.dispatch, ACTION_TURN_OFF)
            assert server.pilot_state["state"] is False
            await _wait_for(lambda: view.title == "WiZ Lighting - Off")
            assert ui_notifications >= 1

            await asyncio.to_thread(tray.dispatch, ACTION_TURN_ON)
            assert server.pilot_state["state"] is True

            # 2. Ajustar brillo desde el submenu de bandeja
            await asyncio.to_thread(tray.dispatch, ACTION_SET_BRIGHTNESS, 25)
            assert server.pilot_state["dimming"] == 25
            await _wait_for(lambda: view.title == "WiZ Lighting - On 25%")

            # 3. Aplicar preset favorito desde la bandeja tras haber cambiado a blanco
            await asyncio.to_thread(bridge.set_temperature, 2700, 90)
            await asyncio.to_thread(tray.dispatch, ACTION_APPLY_PRESET, fav_id)
            assert (
                server.pilot_state["r"],
                server.pilot_state["g"],
                server.pilot_state["b"],
            ) == (10, 210, 140)
            assert server.pilot_state["dimming"] == 65

            # 4. Ocultar y mostrar ventana desde la bandeja
            await asyncio.to_thread(tray.dispatch, ACTION_HIDE_WINDOW)
            assert hide_count == 1
            assert window_visible is False
            await _wait_for(lambda: tray.spec[1].action_id == ACTION_SHOW_WINDOW)

            await asyncio.to_thread(tray.dispatch, ACTION_SHOW_WINDOW)
            assert show_count == 1
            assert window_visible is True
            await _wait_for(lambda: tray.spec[1].action_id == ACTION_HIDE_WINDOW)

            # 5. Iniciar temporizador desde la UI y cancelarlo desde la bandeja
            await asyncio.to_thread(bridge.start_sleep_timer, 15)
            await asyncio.to_thread(tray.refresh)
            assert any(e.action_id == ACTION_CANCEL_SLEEP_TIMER for e in tray.spec)

            await asyncio.to_thread(tray.dispatch, ACTION_CANCEL_SLEEP_TIMER)
            await _wait_for(
                lambda: all(e.action_id != ACTION_CANCEL_SLEEP_TIMER for e in tray.spec)
            )

            # 6. Un cambio originado en la UI dispara el listener y llega a la vista
            previous_applies = len(view.applies)
            await asyncio.to_thread(bridge.set_color, 80, 120, 250, 50)
            await _wait_for(lambda: len(view.applies) > previous_applies)
            assert len(view.applies) > previous_applies
            assert view.title == "WiZ Lighting - On 50%"

            # 7. El tema oscuro de la app cambia la paleta que recibe la vista
            await asyncio.to_thread(bridge.set_theme, "atmospheric-dark")
            await _wait_for(lambda: view.theme == "atmospheric-dark")

            # 8. Accion Quit
            await asyncio.to_thread(tray.dispatch, ACTION_QUIT)
            assert quit_count == 1
        finally:
            tray.stop()
            assert views[0].stop_called is True
            bridge.shutdown()


def test_view_receives_the_snapshot_theme() -> None:
    """El controlador propaga el tema del snapshot a la vista (paleta del menu)."""
    with _TrayHarness() as harness:
        assert harness.view.theme == "architectural-stone"
        harness.actions.snapshot["theme"] = "atmospheric-dark"
        harness.tray.refresh()
        assert harness.view.theme == "atmospheric-dark"
        # Sin tema en el snapshot se cae al tema por defecto de la aplicacion.
        harness.actions.snapshot.pop("theme")
        harness.tray.refresh()
        assert harness.view.theme == "architectural-stone"


def test_refresh_is_the_only_thread_that_applies_native_state() -> None:
    """Una accion del menu nunca aplica estado: lo hace el hilo de refresco."""
    with _TrayHarness(poll_interval=3600.0) as harness:
        harness.view.applied_threads.clear()
        harness.view.applies.clear()

        harness.tray.dispatch(ACTION_TURN_OFF)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not harness.view.applies:
            time.sleep(POLL_SECONDS)

        assert harness.view.applies, "the refresh thread never applied the state"
        assert set(harness.view.applied_threads) == {REFRESH_THREAD_NAME}


def test_stop_is_idempotent_and_stops_the_view() -> None:
    """`stop` retira la vista una sola vez aunque se invoque desde varios hilos."""
    with _TrayHarness() as harness:
        harness.tray.stop()
        harness.tray.stop()
        assert harness.view.stop_called is True


def test_start_does_not_create_a_second_view() -> None:
    """`start` es idempotente: una sola vista y una sola aplicacion inicial."""
    with _TrayHarness() as harness:
        harness.tray.start()
        assert len(harness.views) == 1
        assert harness.tray.view is harness.view


def test_controller_without_a_view_never_applies_state() -> None:
    """Sin vista disponible el controlador no falla: solo deja de aplicar estado."""
    actions = FakeTrayActions()
    tray = TrayController(
        actions,
        show_window=lambda: None,
        hide_window=lambda: None,
        quit_app=lambda: None,
        is_window_visible=lambda: True,
        view_factory=lambda _dispatch: None,
        executor=lambda task: task(),
        poll_interval=0.0,
    )
    tray.start()
    assert tray.view is None
    tray.refresh()
    tray.stop()


# --- Vista de respaldo basada en pystray ------------------------------------------------


class _PystrayHarness:
    """Vista de respaldo ya arrancada, con icono falso y menu abierto controlable."""

    def __init__(self, *, menu_open: bool = False) -> None:
        self.icons: list[FakeTrayIcon] = []
        self.dispatched: list[tuple[str, Any]] = []
        self.menu_open = menu_open
        self.view = PystrayTrayView(
            self._dispatch,
            icon_factory=self._icon_factory,
            menu_is_open=lambda: self.menu_open,
        )

    def _dispatch(self, action_id: str, payload: Any) -> None:
        self.dispatched.append((action_id, payload))

    def _icon_factory(self, name: str, image: Any, title: str, menu: Any) -> FakeTrayIcon:
        icon = FakeTrayIcon(name, image, title, menu)
        self.icons.append(icon)
        return icon

    def start(self) -> None:
        threading.Thread(target=self.view.run, name="PystrayViewTest", daemon=True).start()
        deadline = time.monotonic() + 2.0
        # El icono se asigna a la vista justo antes de `run`, asi que esperar a que el bombeo
        # haya empezado garantiza que la vista ya lo tiene vigente.
        while time.monotonic() < deadline and not (self.icons and self.icons[0].run_called):
            time.sleep(POLL_SECONDS)

    @property
    def icon(self) -> FakeTrayIcon:
        assert self.icons, "the pystray view never created an icon"
        return self.icons[0]

    def apply(self, spec: list[TrayMenuEntry], title: str = "t") -> None:
        self.view.apply(spec, title, (10, 20, 30), "architectural-stone")


def _pystray_spec(**overrides: Any) -> list[TrayMenuEntry]:
    params: dict[str, Any] = {
        "is_on": False,
        "brightness": 100,
        "presets": [TrayPreset(id="p1", name="Warm Desk", is_favorite=True)],
        "window_visible": True,
        "sleep_timer_active": False,
    }
    params.update(overrides)
    return build_tray_menu_spec(**params)


def test_pystray_view_rebuilds_the_native_menu_while_no_menu_is_open() -> None:
    """La vista de respaldo aplica imagen, tooltip y menu cuando no hay popup abierto."""
    harness = _PystrayHarness()
    harness.start()
    harness.apply(_pystray_spec(is_on=True))
    assert harness.icon.title == "t"
    assert harness.icon.update_menu_count == 1
    # Un estado identico no vuelve a destruir/recrear el HMENU.
    harness.apply(_pystray_spec(is_on=True))
    assert harness.icon.update_menu_count == 1


def test_pystray_view_defers_the_rebuild_while_the_popup_is_open() -> None:
    """Regresion: destruir el HMENU con el menu abierto deja todos los items muertos."""
    harness = _PystrayHarness(menu_open=True)
    harness.start()
    harness.apply(_pystray_spec(is_on=True))
    assert harness.icon.update_menu_count == 0

    # Al cerrarse el menu, el proximo `apply` (mismo estado) reintenta el rebuild.
    harness.menu_open = False
    harness.apply(_pystray_spec(is_on=True))
    assert harness.icon.update_menu_count == 1


def _find_menu_item(menu: Any, text: str) -> Any:
    """Busca un item (hoja o padre) en todo el arbol del menu construido."""
    for item in menu:
        if item.text == text:
            return item
        submenu = item.submenu
        if submenu is not None:
            try:
                return _find_menu_item(submenu, text)
            except AssertionError:
                continue
    raise AssertionError(f"Menu item '{text}' not found")


def test_pystray_menu_items_dispatch_every_leaf_action() -> None:
    """Cada hoja del menu construido ejecuta su accion (Encender, Brillo, Preset, Salir)."""
    harness = _PystrayHarness()
    harness.start()
    harness.apply(
        _pystray_spec(presets=[TrayPreset(id="p1", name="Warm Desk", is_favorite=True)]),
    )
    menu = harness.icon.menu
    for label in ("Turn on", "Hide window", "25%", "Warm Desk", "Quit"):
        _find_menu_item(menu, label)(object())

    assert harness.dispatched == [
        (ACTION_TURN_ON, None),
        (WINDOW_TOGGLE_ACTION, None),
        (ACTION_SET_BRIGHTNESS, 25),
        (ACTION_APPLY_PRESET, "p1"),
        (ACTION_QUIT, None),
    ]


def test_pystray_submenu_parents_are_populated_and_do_not_dispatch() -> None:
    """Brillo y Escenas favoritas deben exponer submenus reales con items."""
    harness = _PystrayHarness()
    harness.start()
    harness.apply(_pystray_spec())
    for label in ("Brightness", "Favorite presets"):
        parent = _find_menu_item(harness.icon.menu, label)
        submenu = parent.submenu
        assert submenu is not None, f"{label} must be a submenu"
        assert len(list(submenu)) > 0, f"{label} submenu must not be empty"
        parent(object())

    assert harness.dispatched == []


def test_pystray_view_is_the_exported_factory() -> None:
    """`create_pystray_view` devuelve una vista que cumple el contrato con el despacho dado."""
    dispatched: list[tuple[str, Any]] = []
    view = create_pystray_view(lambda action_id, payload: dispatched.append((action_id, payload)))
    assert isinstance(view, PystrayTrayView)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="owned-popup icon subclassing is Windows-only",
)
def test_icon_factory_owns_the_popup_menu_on_windows() -> None:
    """El popup debe mostrarse con la ventana del icono como dueña.

    pystray usa una segunda ventana invisible como owner, que nunca es la ventana en
    primer plano: con ese owner Windows no auto-despliega los submenus al pasar el cursor
    y hay que hacer clic. La subclase solo redefine `_on_notify` para pasar la ventana ya
    activada, y debe degradar al icono estandar si los internals cambian.
    """
    import pystray

    icon_class = _owner_popup_icon_class()
    assert icon_class is not None
    assert issubclass(icon_class, pystray.Icon)
    assert icon_class is not pystray.Icon
    assert icon_class._on_notify is not pystray.Icon._on_notify
    # `_message_handlers` se arma en __init__ con metodos ligados al objeto, asi que la
    # subclase se usa de verdad para WM_NOTIFY.
    assert icon_class.__dict__["_on_notify"] is not None
