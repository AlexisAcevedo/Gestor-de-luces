"""Raiz de composicion (Composition Root) de la aplicacion de escritorio.

Este modulo ensambla las capas de la Arquitectura Hexagonal inyectando las
implementaciones concretas de infraestructura (`WizUdpController`) en los casos
de uso (`LightControlService`) y exponiendolos a los adaptadores primarios de
ventana nativa (`WebviewBridge` + `pywebview`) y bandeja del sistema (`TrayController`).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from gestor_luces.adapters.ambilight.mss_sampler import MssScreenSampler
from gestor_luces.adapters.audio.wasapi_sampler import WasapiLoopbackSampler
from gestor_luces.adapters.platform.windows import (
    DARK_TITLEBAR_ENABLED,
    THEME_WINDOW_CHROME,
    WINDOW_DEFAULT_SIZE,
    WINDOW_FALLBACK_SIZE,
    WINDOW_MIN_SIZE,
    _activate_window_foreground,
    _compute_fit_height,
    _compute_initial_window_geometry,
    _fit_native_window_height,
    _resolve_native_hwnd,
    _set_windows_dark_titlebar_attribute,
    _sync_native_menu,
    _to_webview_menus,
    show_message_box,
)
from gestor_luces.adapters.storage.json_repositories import (
    JsonBulbRepository,
    JsonSceneRepository,
    JsonSettingsRepository,
    resolve_default_data_dir,
)
from gestor_luces.adapters.system.single_instance import SingleInstanceGuard
from gestor_luces.adapters.system.windows_autostart import WindowsRegistryAutostart
from gestor_luces.adapters.tray import TrayController
from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService
from gestor_luces.desktop import DesktopApplication
from gestor_luces.ports.autostart import AutostartManager
from gestor_luces.resources import resolve_asset_path, resolve_resource_root

# Reexportes de la capa de plataforma Windows: las pruebas y los consumidores historicos
# importan estos simbolos desde `gestor_luces.main`.
__all__ = [
    "DARK_TITLEBAR_ENABLED",
    "THEME_WINDOW_CHROME",
    "WINDOW_DEFAULT_SIZE",
    "WINDOW_FALLBACK_SIZE",
    "WINDOW_MIN_SIZE",
    "_activate_window_foreground",
    "_compute_fit_height",
    "_compute_initial_window_geometry",
    "_fit_native_window_height",
    "_resolve_native_hwnd",
    "_set_windows_dark_titlebar_attribute",
    "_sync_native_menu",
    "_to_webview_menus",
    "build_application",
    "main",
    "parse_args",
    "resolve_icon_path",
    "resolve_png_icon_path",
    "resolve_ui_directory",
    "show_message_box",
]

_LOGGER = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configura el logger raiz con salida a archivo y a stderr.

    Escribe en `<data_dir>/gestor_luces.log` (resuelto con `resolve_default_data_dir`) y
    refleja todo en stderr, para que los mensajes de arranque y de error queden
    disponibles tanto en una consola como en el log persistente de la aplicacion.
    """
    root = logging.getLogger()
    if root.handlers:
        return
    data_dir = resolve_default_data_dir()
    log_path = data_dir / "gestor_luces.log"
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


class _NoopTrayView:
    """Vista de bandeja simulada, sin efectos secundarios, para el smoke-test.

    Cumple el mismo contrato `TrayView` que las vistas reales (`run`, `stop`, `apply`) y
    registra lo aplicado, asi que el smoke-test ejercita el cableado del controlador sin
    abrir ningun toolkit grafico.
    """

    def __init__(self) -> None:
        self.applies: list[tuple[list[Any], str]] = []

    def run(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def apply(self, spec: list[Any], title: str, rgb: tuple[int, int, int], theme: str) -> None:
        self.applies.append((list(spec), title))


def resolve_ui_directory() -> Path:
    """Localiza el directorio `ui/` relativo a la raiz del proyecto (o al bundle de PyInstaller)."""
    return resolve_resource_root() / "ui"


def resolve_icon_path() -> Path:
    """Path of the multi-size application icon shipped in `assets/icon`."""
    return resolve_asset_path("icon", "app.ico")


def resolve_png_icon_path() -> Path:
    """Path of the PNG version of the application icon."""
    return resolve_asset_path("icon", "app.png")


def _default_autostart() -> AutostartManager | None:
    """Registry-backed autostart on Windows; None elsewhere (feature unavailable)."""
    if sys.platform != "win32":
        return None
    return WindowsRegistryAutostart()


def build_application(
    data_dir: Path | None = None,
    autostart: AutostartManager | None = None,
) -> tuple[LightControlService, WebviewBridge]:
    """Instancia y conecta los repositorios JSON, el controlador UDP, el servicio y el puente JS."""
    storage_dir = data_dir if data_dir is not None else resolve_default_data_dir()
    bulb_repo = JsonBulbRepository(data_dir=storage_dir)
    scene_repo = JsonSceneRepository(data_dir=storage_dir)
    settings_repo = JsonSettingsRepository(data_dir=storage_dir)
    controller = WizUdpController()
    service = LightControlService(
        controller=controller,
        bulb_repository=bulb_repo,
        scene_repository=scene_repo,
        settings_repository=settings_repo,
        screen_sampler_factory=MssScreenSampler,
        audio_sampler_factory=WasapiLoopbackSampler,
    )
    bridge = WebviewBridge(
        service=service,
        autostart=autostart if autostart is not None else _default_autostart(),
    )
    return service, bridge


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Procesa los argumentos de linea de comandos para ejecucion normal o smoke test."""
    parser = argparse.ArgumentParser(
        prog="gestor-luces",
        description="WiZ Architectural Lighting Console desktop application.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable pywebview inspector and developer tools.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Verify composition root and UI assets without opening the native GUI loop.",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Start hidden in the system tray (used by the Start with Windows entry).",
    )
    parser.add_argument(
        "--multi-instance",
        action="store_true",
        help=(
            "Bypass single-instance mutex and use an isolated WebView2 profile "
            "for side-by-side comparison."
        ),
    )
    return parser.parse_args(argv)


def _ui_asset_paths(ui_dir: Path) -> dict[str, Path]:
    """Assets de la UI verificados por el smoke test y servidos por la ventana nativa."""
    return {
        "index": ui_dir / "index.html",
        "themes": ui_dir / "themes.css",
        "styles": ui_dir / "styles.css",
        "i18n": ui_dir / "i18n.js",
        "script": ui_dir / "js" / "app.js",
        "scenes": ui_dir / "scenes.json",
    }


def _run_smoke_test(bridge: WebviewBridge) -> int:
    """Ensambla la bandeja con una vista simulada y verifica la UI sin abrir el bucle nativo."""
    ui_dir = resolve_ui_directory()
    assets = _ui_asset_paths(ui_dir)
    icon_path = resolve_icon_path()
    png_icon_path = resolve_png_icon_path()
    smoke_tray = TrayController(
        bridge,
        show_window=lambda: None,
        hide_window=lambda: None,
        quit_app=lambda: None,
        is_window_visible=lambda: True,
        view_factory=lambda dispatch: _NoopTrayView(),
        executor=lambda task: task(),
        poll_interval=0.0,
    )
    bridge.set_state_change_listener(smoke_tray.request_refresh)
    index_path = assets["index"]
    try:
        missing = [
            str(path) for path in (*assets.values(), icon_path, png_icon_path) if not path.is_file()
        ]
        if missing:
            _LOGGER.error("Smoke test failed: missing assets: %s", missing)
            return 1
        smoke_tray.refresh()
        if not smoke_tray.spec:
            _LOGGER.error("Smoke test failed: tray menu specification is empty.")
            return 1
        _LOGGER.info("Composition root initialized. UI entry verified at: %s", index_path)
        return 0
    finally:
        smoke_tray.stop()
        bridge.shutdown()


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada principal de la aplicacion de escritorio."""
    _configure_logging()
    args = parse_args(argv)
    ui_dir = resolve_ui_directory()
    index_path = ui_dir / "index.html"
    icon_path = resolve_icon_path()

    guard: SingleInstanceGuard | None = None
    if not args.smoke_test and not getattr(args, "multi_instance", False):
        guard = SingleInstanceGuard()
        if not guard.acquire():
            _LOGGER.info(
                "An existing Gestor de luces instance is already running; "
                "bringing it to the foreground. "
                "(Pass --multi-instance to launch a side-by-side window.)"
            )
            guard.signal_existing_instance()
            return 0

    autostart = _default_autostart()
    service, bridge = build_application(autostart=autostart)

    if args.smoke_test:
        return _run_smoke_test(bridge)

    app = DesktopApplication(
        service=service,
        bridge=bridge,
        index_path=index_path,
        icon_path=icon_path,
        ui_dir=ui_dir,
        debug=args.debug,
        minimized=args.minimized,
        multi_instance=getattr(args, "multi_instance", False),
        guard=guard,
        autostart=autostart,
    )
    app.create_window()
    win_width, win_height = app.window_size
    _LOGGER.info("Opening UI window (%sx%s) -> %s", win_width, win_height, index_path)
    app.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
