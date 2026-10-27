"""Raiz de composicion (Composition Root) de la aplicacion de escritorio.

Este modulo ensambla las capas de la Arquitectura Hexagonal inyectando las
implementaciones concretas de infraestructura (`WizUdpController`) en los casos
de uso (`LightControlService`) y exponiendolos a los adaptadores primarios de
ventana nativa (`WebviewBridge` + `pywebview`) y bandeja del sistema (`TrayController`).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
from typing import Any

from gestor_luces.adapters.ambilight import MssScreenSampler
from gestor_luces.adapters.audio import WasapiLoopbackSampler
from gestor_luces.adapters.storage.json_repositories import (
    JsonBulbRepository,
    JsonSceneRepository,
    JsonSettingsRepository,
    resolve_default_data_dir,
)
from gestor_luces.adapters.tray import TrayController
from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService

_LOGGER = logging.getLogger(__name__)


WINDOW_MIN_SIZE = (760, 560)
WINDOW_FALLBACK_SIZE = (1180, 780)
WINDOW_MAX_SIZE = (1440, 920)
WINDOW_SCREEN_RATIO = 0.9


def _compute_initial_window_geometry(webview_module: object) -> tuple[int, int, int | None, int | None]:
    """Return (width, height, x, y) sized to ~90% of the primary screen and centered.

    Falls back to the legacy fixed size (OS-centered) when screen info is unavailable.
    """
    try:
        screens = getattr(webview_module, "screens", None)
        if not screens:
            raise RuntimeError("no screens reported")
        screen = screens[0]
        screen_w, screen_h = int(screen.width), int(screen.height)
        if screen_w <= 0 or screen_h <= 0:
            raise RuntimeError("invalid screen size")
    except Exception:
        return (*WINDOW_FALLBACK_SIZE, None, None)

    width = int(screen_w * WINDOW_SCREEN_RATIO)
    height = int(screen_h * WINDOW_SCREEN_RATIO)
    width = max(WINDOW_MIN_SIZE[0], min(width, WINDOW_MAX_SIZE[0], screen_w))
    height = max(WINDOW_MIN_SIZE[1], min(height, WINDOW_MAX_SIZE[1], screen_h))
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    return width, height, x, y



class _NoopTrayIcon:
    """Icono simulado sin efectos secundarios para verificar el ensamblado en smoke-test."""

    def __init__(self, name: str, image: Any, title: str, menu: Any) -> None:
        self.name = name
        self.icon = image
        self.title = title
        self.menu = menu

    def run(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def update_menu(self) -> None:
        return None


def resolve_ui_directory() -> Path:
    """Localiza el directorio `ui/` relativo a la raiz del proyecto."""
    return Path(__file__).resolve().parents[2] / "ui"


def build_application(
    data_dir: Path | None = None,
) -> tuple[LightControlService, WebviewBridge]:
    """Instancia y conecta los repositorios JSON, el controlador UDP, el servicio y el puente JS."""
    storage_dir = data_dir if data_dir is not None else resolve_default_data_dir()
    bulb_repo = JsonBulbRepository(data_dir=storage_dir)
    scene_repo = JsonSceneRepository(data_dir=storage_dir)
    settings_repo = JsonSettingsRepository(data_dir=storage_dir)
    controller = WizUdpController()
    screen_sampler = MssScreenSampler()
    audio_sampler = WasapiLoopbackSampler()
    service = LightControlService(
        controller=controller,
        bulb_repository=bulb_repo,
        scene_repository=scene_repo,
        screen_sampler=screen_sampler,
        audio_sampler=audio_sampler,
        settings_repository=settings_repo,
    )
    bridge = WebviewBridge(service=service)
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada principal de la aplicacion de escritorio."""
    args = parse_args(argv)
    ui_dir = resolve_ui_directory()
    index_path = ui_dir / "index.html"
    styles_path = ui_dir / "styles.css"
    i18n_path = ui_dir / "i18n.js"
    script_path = ui_dir / "app.js"

    _, bridge = build_application()

    if args.smoke_test:
        smoke_tray = TrayController(
            bridge,
            show_window=lambda: None,
            hide_window=lambda: None,
            quit_app=lambda: None,
            is_window_visible=lambda: True,
            icon_factory=_NoopTrayIcon,
            executor=lambda task: task(),
            poll_interval=0.0,
        )
        bridge.set_state_change_listener(smoke_tray.request_refresh)
        try:
            missing = [
                str(p)
                for p in (index_path, styles_path, i18n_path, script_path)
                if not p.is_file()
            ]
            if missing:
                print(f"Smoke test failed: missing UI assets: {missing}", file=sys.stderr)
                return 1
            smoke_tray.refresh()
            if not smoke_tray.spec:
                print("Smoke test failed: tray menu specification is empty.", file=sys.stderr)
                return 1
            print(f"Composition root initialized. UI entry verified at: {index_path}")
            return 0
        finally:
            smoke_tray.stop()
            bridge.shutdown()

    import webview

    is_window_visible = True
    is_quitting = False
    tray: TrayController | None = None

    win_width, win_height, win_x, win_y = _compute_initial_window_geometry(webview)

    window = webview.create_window(
        title="WiZ Architectural Lighting Console",
        url=index_path.as_uri(),
        js_api=bridge,
        width=win_width,
        height=win_height,
        x=win_x,
        y=win_y,
        min_size=(WINDOW_MIN_SIZE[0], WINDOW_MIN_SIZE[1]),
        background_color="#0D0F12",
    )

    def _apply_windows_dark_titlebar() -> None:
        """Activa el atributo DWMWA_USE_IMMERSIVE_DARK_MODE (20) en Windows 10/11.

        Garantiza que la barra de titulo nativa de Win32/WinForms se pinte en modo
        oscuro para integrarse visualmente con el chasis #0D0F12 de la consola.
        """
        if sys.platform != "win32":
            return
        try:
            native_form = getattr(window, "native", None)
            if native_form is not None:
                import ctypes

                hwnd = native_form.Handle.ToInt32()
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    20,
                    ctypes.byref(ctypes.c_int(1)),
                    ctypes.sizeof(ctypes.c_int),
                )
        except Exception:
            _LOGGER.debug("Windows dark titlebar attribute skipped.")

    def show_window() -> None:
        """Restaura la ventana desde la bandeja y la trae al frente en Windows."""
        nonlocal is_window_visible
        is_window_visible = True
        window.show()
        try:
            window.restore()
        except Exception:
            _LOGGER.debug("Window restore skipped because window was not minimized.")
        _apply_windows_dark_titlebar()
        try:
            native_form = getattr(window, "native", None)
            if native_form is not None:
                import ctypes

                hwnd = native_form.Handle.ToInt32()
                # SW_RESTORE (9) asegura que deje el estado minimizado/oculto y SetForegroundWindow
                # le devuelve el foco tras cerrar el menu popup de la bandeja.
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            _LOGGER.debug("Native foreground activation skipped.")
        if tray is not None:
            tray.request_refresh()

    def hide_window() -> None:
        """Oculta la ventana en la bandeja manteniendo vivos el bucle UDP y los temporizadores."""
        nonlocal is_window_visible
        is_window_visible = False
        window.hide()
        if tray is not None:
            tray.request_refresh()

    def notify_ui() -> None:
        """Avisa a la vista web que una accion de la bandeja modifico el estado luminico."""
        if not is_window_visible or is_quitting:
            return
        try:
            window.evaluate_js("window.onTrayStateChanged && window.onTrayStateChanged()")
        except Exception:
            _LOGGER.debug("Skipped UI notification because webview was not ready.")

    def quit_app() -> None:
        """Autoriza el cierre definitivo de la ventana y libera la bandeja y el bucle UDP."""
        nonlocal is_quitting
        is_quitting = True
        if tray is not None:
            tray.stop()
        bridge.shutdown()
        try:
            window.destroy()
        except Exception:
            _LOGGER.debug("Window destroy skipped because window was already closed.")

    def on_closing() -> bool:
        """Intercepta el boton [X] para minimizar a la bandeja salvo cuando se invoca Quit.

        Importante en WinForms/pywebview: `window.events.closing` se ejecuta de forma
        sincrona en el hilo principal de la ventana (`should_lock=True`). Llamar a
        `window.hide()` directamente dentro de `FormClosing` puede reentrar o bloquear
        con `self.Invoke(self.Hide)`. Por eso despachamos `hide_window` en un hilo corto
        apenas `on_closing` devuelve `False` (`args.Cancel = True`).
        """
        if not is_quitting:
            import threading

            threading.Thread(target=hide_window, name="GestorLucesHideOnClose", daemon=True).start()
            return False
        return True

    def on_minimized() -> None:
        """Cuando el usuario minimiza la ventana con [_], la enviamos a la bandeja."""
        if not is_quitting and is_window_visible:
            import threading

            threading.Thread(
                target=hide_window,
                name="GestorLucesHideOnMinimize",
                daemon=True,
            ).start()

    def on_closed() -> None:
        """Garantiza la liberacion de recursos si el sistema operativo cierra la ventana."""
        if tray is not None:
            tray.stop()
        bridge.shutdown()

    tray = TrayController(
        bridge,
        show_window=show_window,
        hide_window=hide_window,
        quit_app=quit_app,
        is_window_visible=lambda: is_window_visible,
        notify_ui=notify_ui,
    )
    bridge.set_state_change_listener(tray.request_refresh)
    window.events.shown += _apply_windows_dark_titlebar
    window.events.closing += on_closing
    window.events.minimized += on_minimized
    window.events.closed += on_closed

    tray.start()
    try:
        webview.start(debug=args.debug)
    finally:
        tray.stop()
        bridge.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
