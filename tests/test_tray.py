"""Pruebas unitarias y de integracion para el adaptador de bandeja del sistema (Fase 5).

Cubre dos niveles complementarios:
1. Pruebas rapidas y deterministas sobre el modelo puro (`menu_model`) y el generador
   de iconos (`render_icon_image`), sin hilos ni sockets.
2. Pruebas de integracion extremo a extremo que conectan `TrayController`,
   `WebviewBridge`, `LightControlService`, `WizUdpController` y `FakeWizBulbServer`
   para garantizar que las acciones del menu modifiquen el foco UDP real y que los
   cambios originados en la UI actualicen inmediatamente la bandeja.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

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
from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer


class FakeTrayIcon:
    """Doble de prueba de `pystray.Icon` para inspeccionar estado sin abrir Win32."""

    def __init__(self, name: str, image: Any, title: str, menu: Any) -> None:
        self.name = name
        self.icon = image
        self.title = title
        self.menu = menu
        self.run_called = False
        self.stop_called = False
        self.update_menu_count = 0

    def run(self) -> None:
        self.run_called = True

    def stop(self) -> None:
        self.stop_called = True

    def update_menu(self) -> None:
        self.update_menu_count += 1


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
        TrayPreset(id=f"p{idx}", name=f"Preset {idx}", is_favorite=False)
        for idx in range(12)
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


def test_resolve_icon_rgb_and_render_icon_image() -> None:
    """Verifica el calculo del color del icono por modo y la generacion RGBA 64x64."""
    assert (
        resolve_icon_rgb(is_on=False, mode="rgb", color=[255, 0, 0], temperature=None)
        == OFF_ICON_RGB
    )
    assert resolve_icon_rgb(
        is_on=True, mode="rgb", color=[12, 200, 95], temperature=None
    ) == (12, 200, 95)
    assert (
        resolve_icon_rgb(is_on=True, mode="scene", color=None, temperature=None)
        == SCENE_ICON_RGB
    )

    warm_rgb = resolve_icon_rgb(
        is_on=True, mode="temperature", color=None, temperature=2200
    )
    cool_rgb = resolve_icon_rgb(
        is_on=True, mode="temperature", color=None, temperature=6500
    )
    assert warm_rgb == (255, 180, 107)
    assert cool_rgb == (214, 232, 255)

    img = render_icon_image((20, 180, 240))
    assert img.mode == "RGBA"
    assert img.size == (64, 64)
    center_pixel = img.getpixel((32, 32))
    assert center_pixel[:3] == (20, 180, 240)
    assert center_pixel[3] == 255
    corner_pixel = img.getpixel((0, 0))
    assert corner_pixel[3] == 0


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

        created_icons: list[FakeTrayIcon] = []
        window_visible = True
        show_count = 0
        hide_count = 0
        quit_count = 0
        ui_notifications = 0

        def fake_icon_factory(
            name: str, image: Any, title: str, menu: Any
        ) -> FakeTrayIcon:
            icon = FakeTrayIcon(name, image, title, menu)
            created_icons.append(icon)
            return icon

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
            icon_factory=fake_icon_factory,
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
            fav_id = next(
                s["id"] for s in scenes_env["custom_scenes"] if s["name"] == "Mint Focus"
            )
            await asyncio.to_thread(bridge.set_custom_scene_favorite, fav_id, True)

            await asyncio.to_thread(tray.start)
            assert len(created_icons) == 1
            fake_icon = created_icons[0]
            assert fake_icon.title == "WiZ Lighting - On 65%"

            # El submenu de presets favoritos solo expone el preset marcado como favorito
            presets_menu = _find_entry_by_label(tray.spec, "Favorite presets")
            assert [c.label for c in presets_menu.children] == ["Mint Focus"]

            # 1. Apagar y volver a encender desde el menu de bandeja
            await asyncio.to_thread(tray.dispatch, ACTION_TURN_OFF)
            assert server.pilot_state["state"] is False
            assert fake_icon.title == "WiZ Lighting - Off"
            assert ui_notifications >= 1

            await asyncio.to_thread(tray.dispatch, ACTION_TURN_ON)
            assert server.pilot_state["state"] is True

            # 2. Ajustar brillo desde el submenu de bandeja
            await asyncio.to_thread(tray.dispatch, ACTION_SET_BRIGHTNESS, 25)
            assert server.pilot_state["dimming"] == 25
            assert fake_icon.title == "WiZ Lighting - On 25%"

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
            assert tray.spec[1].action_id == ACTION_SHOW_WINDOW

            await asyncio.to_thread(tray.dispatch, ACTION_SHOW_WINDOW)
            assert show_count == 1
            assert window_visible is True
            assert tray.spec[1].action_id == ACTION_HIDE_WINDOW

            # 5. Iniciar temporizador desde la UI y cancelarlo desde la bandeja
            await asyncio.to_thread(bridge.start_sleep_timer, 15)
            await asyncio.to_thread(tray.refresh)
            assert any(
                e.action_id == ACTION_CANCEL_SLEEP_TIMER for e in tray.spec
            )

            await asyncio.to_thread(tray.dispatch, ACTION_CANCEL_SLEEP_TIMER)
            assert all(
                e.action_id != ACTION_CANCEL_SLEEP_TIMER for e in tray.spec
            )

            # 6. Verificar que un cambio originado en la UI dispare el listener de bandeja
            prev_updates = fake_icon.update_menu_count
            await asyncio.to_thread(bridge.set_color, 80, 120, 250, 50)
            await asyncio.sleep(0.12)
            assert fake_icon.update_menu_count > prev_updates
            assert fake_icon.title == "WiZ Lighting - On 50%"

            # 7. Accion Quit
            await asyncio.to_thread(tray.dispatch, ACTION_QUIT)
            assert quit_count == 1
        finally:
            tray.stop()
            assert created_icons[0].stop_called is True
            bridge.shutdown()
