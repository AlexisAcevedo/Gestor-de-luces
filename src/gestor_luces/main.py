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
import threading
from typing import Any

from gestor_luces.adapters.storage.json_repositories import (
    JsonBulbRepository,
    JsonSceneRepository,
    JsonSettingsRepository,
    resolve_default_data_dir,
)
from gestor_luces.adapters.system.single_instance import SingleInstanceGuard
from gestor_luces.adapters.system.windows_autostart import WindowsRegistryAutostart
from gestor_luces.adapters.ui_webview.app_menu import (
    ACTION_EXIT,
    ACTION_SHOW_ABOUT,
    ACTION_SHOW_SHORTCUTS,
    ACTION_TOGGLE_AUTOSTART,
    ACTION_TOGGLE_WINDOW,
    APP_DISPLAY_NAME,
    AppMenu,
    build_about_text,
    build_app_menu,
)
from gestor_luces.adapters.ui_webview.bridge import JsApi, WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService
from gestor_luces.ports.autostart import AutostartManager
from gestor_luces.resources import resolve_app_version, resolve_asset_path, resolve_resource_root

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

    def _apply() -> None:
        strip = next(
            (c for c in native_form.Controls if c.GetType().Name == "MenuStrip"),
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
    except Exception:
        _LOGGER.debug("Native menu sync skipped.", exc_info=True)


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada principal de la aplicacion de escritorio."""
    args = parse_args(argv)
    ui_dir = resolve_ui_directory()
    index_path = ui_dir / "index.html"
    styles_path = ui_dir / "styles.css"
    i18n_path = ui_dir / "i18n.js"
    script_path = ui_dir / "app.js"

    icon_path = resolve_icon_path()
    png_icon_path = resolve_png_icon_path()

    guard: SingleInstanceGuard | None = None
    if not args.smoke_test:
        guard = SingleInstanceGuard()
        if not guard.acquire():
            guard.signal_existing_instance()
            return 0

    autostart = _default_autostart()
    _, bridge = build_application(autostart=autostart)

    
    from gestor_luces.adapters.tray import TrayController

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
                for p in (
                    index_path,
                    styles_path,
                    i18n_path,
                    script_path,
                    icon_path,
                    png_icon_path,
                )
                if not p.is_file()
            ]
            if missing:
                print(f"Smoke test failed: missing assets: {missing}", file=sys.stderr)
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

    # Keep a portable build's autostart entry pointing at the current location.
    try:
        if autostart is not None and autostart.refresh_if_stale():
            _LOGGER.info("Autostart entry was stale and has been refreshed.")
    except Exception:
        _LOGGER.exception("Autostart refresh failed.")

    is_window_visible = not args.minimized
    is_quitting = False
    tray: TrayController | None = None
    menu_sync_requested = threading.Event()

    win_width, win_height, win_x, win_y = _compute_initial_window_geometry(webview)

    window = webview.create_window(
        title="WiZ Architectural Lighting Console",
        url=index_path.as_uri(),
        js_api=JsApi(bridge),
        width=win_width,
        height=win_height,
        x=win_x,
        y=win_y,
        min_size=(WINDOW_MIN_SIZE[0], WINDOW_MIN_SIZE[1]),
        background_color="#0D0F12",
        hidden=args.minimized,
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
        menu_sync_requested.set()
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
        menu_sync_requested.set()
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
    def _current_menu_spec() -> list[AppMenu]:
        snapshot = bridge.get_tray_snapshot()
        return build_app_menu(
            language=str(snapshot.get("language") or "en"),
            window_visible=is_window_visible,
            autostart_enabled=bool(bridge.get_autostart().get("enabled")),
        )

    def _menu_sync_worker() -> None:
        """Serialize menu updates off the GUI and bridge-loop threads."""
        while not is_quitting:
            menu_sync_requested.wait()
            menu_sync_requested.clear()
            if is_quitting:
                break
            try:
                _sync_native_menu(window, _current_menu_spec())
            except Exception:
                _LOGGER.debug("Menu refresh skipped.", exc_info=True)

    def request_menu_sync() -> None:
        menu_sync_requested.set()

    def toggle_window() -> None:
        if is_window_visible:
            hide_window()
        else:
            show_window()

    def show_shortcuts() -> None:
        show_window()
        try:
            window.evaluate_js(
                "(function(){var d=document.getElementById('shortcuts-dialog');"
                "if(d&&!d.open){d.showModal();}})()"
            )
        except Exception:
            _LOGGER.debug("Shortcuts dialog could not be opened.")

    def show_about() -> None:
        language = str(bridge.get_tray_snapshot().get("language") or "en")
        text = build_about_text(language, resolve_app_version())
        if sys.platform == "win32":
            import ctypes

            # MB_OK | MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(0, text, APP_DISPLAY_NAME, 0x40)
        else:
            _LOGGER.info("%s", text)

    def toggle_autostart() -> None:
        current = bool(bridge.get_autostart().get("enabled"))
        result = bridge.set_autostart(not current)
        if not result.get("ok"):
            _LOGGER.warning("Autostart toggle failed: %s", result.get("error"))
        request_menu_sync()

    menu_handlers = {
        ACTION_TOGGLE_WINDOW: toggle_window,
        ACTION_TOGGLE_AUTOSTART: toggle_autostart,
        ACTION_EXIT: quit_app,
        ACTION_SHOW_SHORTCUTS: show_shortcuts,
        ACTION_SHOW_ABOUT: show_about,
    }

    def on_menu_action(action_id: str) -> None:
        handler = menu_handlers.get(action_id)
        if handler is None:
            _LOGGER.warning("Unknown menu action: %s", action_id)
            return
        try:
            handler()
        except Exception:
            _LOGGER.exception("Menu action '%s' failed.", action_id)
        if action_id != ACTION_EXIT:
            request_menu_sync()

    def _on_state_changed() -> None:
        tray.request_refresh()
        request_menu_sync()

    bridge.set_state_change_listener(_on_state_changed)
    window.events.shown += _apply_windows_dark_titlebar
    window.events.shown += request_menu_sync
    window.events.closing += on_closing
    window.events.minimized += on_minimized
    window.events.closed += on_closed

    threading.Thread(target=_menu_sync_worker, name="GestorLucesMenuSync", daemon=True).start()
    if guard is not None:
        guard.listen(show_window)
    tray.start()
    try:
        # private_mode=False + storage_path make localStorage (UI prefs, favorite scenes)
        # persist across launches; WebView2 defaults to an ephemeral profile otherwise.
        webview_storage = resolve_default_data_dir() / "webview"
        webview_storage.mkdir(parents=True, exist_ok=True)
        initial_menu = build_app_menu(
            language=str(bridge.get_tray_snapshot().get("language") or "en"),
            window_visible=is_window_visible,
            autostart_enabled=bool(bridge.get_autostart().get("enabled")),
        )
        webview.start(
            debug=args.debug,
            private_mode=False,
            storage_path=str(webview_storage),
            menu=_to_webview_menus(initial_menu, on_menu_action),
            icon=str(icon_path) if icon_path.is_file() else None,
        )
    finally:
        if guard is not None:
            guard.release()
        tray.stop()
        bridge.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
