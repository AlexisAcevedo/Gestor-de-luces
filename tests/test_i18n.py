"""Pruebas unitarias y de integracion para el soporte bilingue (en / es).

Verifica la persistencia de `JsonSettingsRepository`, la validacion en `LightControlService`,
la propagacion reactiva a traves de `WebviewBridge` hacia el menu de bandeja del sistema
(`menu_model` y `TrayController`) y la integridad de los recursos `ui/i18n.js` e `index.html`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from gestor_luces.adapters.storage.json_repositories import (
    JsonBulbRepository,
    JsonSceneRepository,
    JsonSettingsRepository,
)
from gestor_luces.adapters.tray import (
    TrayController,
    TrayPreset,
    build_tray_menu_spec,
    build_tray_title,
)
from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService
from gestor_luces.main import resolve_ui_directory
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer


class _FakeTrayIcon:
    """Doble de prueba de `pystray.Icon` para inspeccionar el idioma de la bandeja."""

    def __init__(self, name: str, image: Any, title: str, menu: Any) -> None:
        self.name = name
        self.icon = image
        self.title = title
        self.menu = menu
        self.update_menu_count = 0

    def run(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def update_menu(self) -> None:
        self.update_menu_count += 1


def test_json_settings_repository_persists_and_tolerates_corrupt_files(
    tmp_path: Path,
) -> None:
    """Comprueba la persistencia atomica del idioma y el respaldo seguro a `en`."""
    repo = JsonSettingsRepository(data_dir=tmp_path)
    assert repo.load_settings() == {"language": "en"}

    repo.save_settings({"language": "es"})
    assert repo.file_path.is_file()
    assert repo.load_settings() == {"language": "es"}

    # Un codigo no soportado al guardar o leer cae de forma segura a "en"
    repo.file_path.write_text('{"language": "fr"}', encoding="utf-8")
    assert repo.load_settings() == {"language": "en"}

    # Un archivo JSON corrupto no bloquea el arranque y retorna "en"
    repo.file_path.write_text("{corrupt-json", encoding="utf-8")
    assert repo.load_settings() == {"language": "en"}


def test_service_language_persistence_and_validation(tmp_path: Path) -> None:
    """Verifica que LightControlService cargue, valide y persista el idioma activo."""
    settings_repo = JsonSettingsRepository(data_dir=tmp_path)
    controller = WizUdpController(probe_candidates=[])
    service = LightControlService(
        controller=controller,
        settings_repository=settings_repo,
    )
    assert service.get_language() == "en"

    updated = service.set_language("ES")
    assert updated == "es"
    assert service.get_language() == "es"

    # Al instanciar un nuevo servicio sobre el mismo directorio, recupera "es"
    reloaded_service = LightControlService(
        controller=controller,
        settings_repository=JsonSettingsRepository(data_dir=tmp_path),
    )
    assert reloaded_service.get_language() == "es"

    with pytest.raises(ValueError, match="Unsupported language"):
        service.set_language("de")


def test_build_tray_menu_spec_and_title_in_spanish() -> None:
    """Comprueba todas las etiquetas en espanol neutro del menu de bandeja y su tooltip."""
    spec_es_off = build_tray_menu_spec(
        is_on=False,
        brightness=50,
        presets=[],
        window_visible=False,
        sleep_timer_active=False,
        language="es",
    )
    labels_off = [entry.label for entry in spec_es_off if not entry.is_separator]
    assert labels_off == [
        "Encender",
        "Abrir consola",
        "Brillo",
        "Escenas favoritas",
        "Salir",
    ]
    fav_submenu = next(e for e in spec_es_off if e.label == "Escenas favoritas")
    assert fav_submenu.children[0].label == "Sin escenas guardadas"
    assert fav_submenu.children[0].enabled is False

    spec_es_on = build_tray_menu_spec(
        is_on=True,
        brightness=80,
        presets=[TrayPreset(id="p1", name="Lectura Calida", is_favorite=True)],
        window_visible=True,
        sleep_timer_active=True,
        language="es",
    )
    labels_on = [entry.label for entry in spec_es_on if not entry.is_separator]
    assert labels_on == [
        "Apagar",
        "Ocultar ventana",
        "Brillo",
        "Escenas favoritas",
        "Cancelar temporizador",
        "Salir",
    ]
    assert build_tray_title(True, 80, language="es") == "Iluminación WiZ - Encendido 80%"
    assert build_tray_title(False, 80, language="es") == "Iluminación WiZ - Apagado"


async def test_bridge_set_language_updates_tray_controller_immediately(
    tmp_path: Path,
) -> None:
    """Verifica que cambiar el idioma en WebviewBridge actualice al instante el TrayController."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(
            controller=controller,
            bulb_repository=JsonBulbRepository(data_dir=tmp_path),
            scene_repository=JsonSceneRepository(data_dir=tmp_path),
            settings_repository=JsonSettingsRepository(data_dir=tmp_path),
        )
        bridge = WebviewBridge(service=service)
        created_icons: list[_FakeTrayIcon] = []

        tray = TrayController(
            bridge,
            show_window=lambda: None,
            hide_window=lambda: None,
            quit_app=lambda: None,
            is_window_visible=lambda: True,
            icon_factory=lambda name, img, title, menu: (
                icon := _FakeTrayIcon(name, img, title, menu),
                created_icons.append(icon),
                icon,
            )[-1],
            executor=lambda task: task(),
            poll_interval=0.05,
        )
        bridge.set_state_change_listener(tray.request_refresh)

        try:
            init_env = await asyncio.to_thread(bridge.get_initial_state)
            assert init_env["language"] == "en"
            await asyncio.to_thread(bridge.set_power, True, 75)

            await asyncio.to_thread(tray.start)
            assert created_icons[0].title == "WiZ Lighting - On 75%"
            assert tray.spec[1].label == "Hide window"

            # Cambiamos a espanol a traves del puente JS
            es_env = await asyncio.to_thread(bridge.set_language, "es")
            assert es_env["ok"] is True
            assert es_env["language"] == "es"

            await asyncio.to_thread(tray.refresh)
            assert created_icons[0].title == "Iluminación WiZ - Encendido 75%"
            assert tray.spec[1].label == "Ocultar ventana"
            assert any(e.label == "Escenas favoritas" for e in tray.spec)
            assert any(e.label == "Salir" for e in tray.spec)
        finally:
            tray.stop()
            bridge.shutdown()


def test_ui_i18n_assets_and_builtin_scene_names_preserved() -> None:
    """Verifica que `ui/i18n.js` e `index.html` expongan los diccionarios bilingues."""
    ui_dir = resolve_ui_directory()
    i18n_js = (ui_dir / "i18n.js").read_text(encoding="utf-8")
    index_html = (ui_dir / "index.html").read_text(encoding="utf-8")
    app_js = (ui_dir / "app.js").read_text(encoding="utf-8")

    assert "window.I18N" in i18n_js
    assert '"rail.scanBtn": "Scan network"' in i18n_js
    assert '"rail.scanBtn": "Escanear red"' in i18n_js
    assert '"rail.selectAll": "Seleccionar todas"' in i18n_js
    assert '"scenes.catAll": "Todas (36)"' in i18n_js
    assert '"scenes.plantGrowth": "Plant growth"' in i18n_js
    assert '"scenes.plantGrowth": "Crecimiento de plantas"' in i18n_js
    assert '"ambi.minBrightnessLabel": "Piso Mínimo de Brillo"' in i18n_js
    assert '<script src="i18n.js"></script>' in index_html
    assert 'id="lang-btn-en"' in index_html
    assert 'id="lang-btn-es"' in index_html
    assert 'id="sleep-timer-details"' in index_html
    assert 'id="scene-filter-favorites"' in index_html
    assert 'id="ambilight-min-brightness-slider"' in index_html
    assert "SCENE_CHROMATIC_MAP" in app_js
    assert "gestor_luces_fav_scenes" in app_js
    # Los nombres de las 36 escenas nativas de WiZ se mantienen en su denominacion original
    for builtin_name in ("Ocean", "Romance", "Sunset", "Fireplace", "Daylight", "Steampunk", "Plantgrowth"):
        assert f'name: "{builtin_name}"' in app_js

