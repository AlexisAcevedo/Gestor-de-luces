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
import threading
from pathlib import Path
from typing import Any

from gestor_luces.adapters.ambilight.mss_sampler import MssScreenSampler
from gestor_luces.adapters.audio.wasapi_sampler import WasapiLoopbackSampler
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
from gestor_luces.domain.value_objects import DEFAULT_THEME
from gestor_luces.ports.autostart import AutostartManager
from gestor_luces.resources import resolve_app_version, resolve_asset_path, resolve_resource_root

_LOGGER = logging.getLogger(__name__)


WINDOW_DEFAULT_SIZE = (620, 760)
WINDOW_MIN_SIZE = (480, 640)
WINDOW_FALLBACK_SIZE = WINDOW_DEFAULT_SIZE
THEME_WINDOW_CHROME: dict[str, dict[str, Any]] = {
    "architectural-stone": {
        "background_color": "#F4F1EA",
        "dark_titlebar": False,
    },
    "atmospheric-dark": {
        "background_color": "#08090C",
        "dark_titlebar": True,
    },
}
DARK_TITLEBAR_ENABLED = False


def _resolve_native_hwnd(native_form: Any) -> int | None:
    """Extrae el HWND nativo de 64 bits sin truncar punteros mayores a 0x7FFFFFFF."""
    if native_form is None:
        return None
    handle = getattr(native_form, "Handle", None)
    if handle is None:
        return None
    for method_name in ("ToInt64", "ToInt32"):
        converter = getattr(handle, method_name, None)
        if callable(converter):
            try:
                hwnd = int(converter())
                return hwnd if hwnd > 0 else None
            except Exception:
                _LOGGER.debug("Handle.%s() conversion failed.", method_name, exc_info=True)
    try:
        hwnd = int(handle)
        return hwnd if hwnd > 0 else None
    except Exception:
        return None


def _configure_fn_signature(fn: Any, argtypes: list[Any], restype: Any) -> None:
    """Declara `argtypes` y `restype` sobre punteros Win32 reales sin romper dobles de prueba."""
    if fn is None:
        return
    try:
        if hasattr(fn, "argtypes"):
            fn.argtypes = argtypes
        if hasattr(fn, "restype"):
            fn.restype = restype
    except Exception:
        _LOGGER.debug("Win32 function signature setup skipped.", exc_info=True)


def _set_windows_dark_titlebar_attribute(
    window: Any,
    *,
    enabled: bool = DARK_TITLEBAR_ENABLED,
    platform: str = sys.platform,
    dwmapi: Any = None,
) -> bool:
    """Actualiza bidireccionalmente el atributo DWMWA_USE_IMMERSIVE_DARK_MODE (20) en Windows."""
    if platform != "win32":
        return False
    try:
        native_form = getattr(window, "native", None)
        hwnd = _resolve_native_hwnd(native_form)
        if hwnd is None:
            return False
        import ctypes
        from ctypes import wintypes

        target_dwmapi = ctypes.windll.dwmapi if dwmapi is None else dwmapi
        dwm_fn = getattr(target_dwmapi, "DwmSetWindowAttribute", None)
        if dwm_fn is None:
            return False
        _configure_fn_signature(
            dwm_fn,
            [wintypes.HWND, ctypes.c_int, ctypes.c_void_p, ctypes.c_int],
            ctypes.c_int,
        )
        value = ctypes.c_int(1 if enabled else 0)
        dwm_fn(
            hwnd,
            20,
            ctypes.byref(value),
            ctypes.sizeof(ctypes.c_int),
        )
        return True
    except Exception:
        _LOGGER.debug("Windows dark titlebar attribute skipped.", exc_info=True)
        return False


def _compute_initial_window_geometry(
    webview_module: object,
) -> tuple[int, int, int | None, int | None]:
    """Return (width, height, x, y) sized to WINDOW_DEFAULT_SIZE, clamped to screen
    bounds, and centered.

    Falls back to WINDOW_DEFAULT_SIZE (OS-centered) when screen info is unavailable.
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
        return (*WINDOW_DEFAULT_SIZE, None, None)

    width = min(WINDOW_DEFAULT_SIZE[0], screen_w)
    if screen_w >= WINDOW_MIN_SIZE[0]:
        width = max(WINDOW_MIN_SIZE[0], width)

    height = min(WINDOW_DEFAULT_SIZE[1], screen_h)
    if screen_h >= WINDOW_MIN_SIZE[1]:
        height = max(WINDOW_MIN_SIZE[1], height)

    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    return width, height, x, y


def _compute_fit_height(
    content_px: int,
    chrome: float,
    min_h: int = WINDOW_MIN_SIZE[1],
    max_h: int = WINDOW_DEFAULT_SIZE[1],
) -> int:
    """Return the outer window height (logical px) for a page content height.

    `chrome` is the non-client height (title bar + menu bar). The result is clamped to
    `[min_h, max_h]`; when the work area is smaller than `min_h`, the work area wins.
    """
    target = int(round(content_px + chrome))
    return max(1, min(max(target, int(min_h)), int(max_h)))


def _fit_native_window_height(
    window: Any,
    content_px: int,
    fallback_max_h: int | None = None,
    *,
    baseline_height: int = WINDOW_DEFAULT_SIZE[1],
    min_height: int = WINDOW_MIN_SIZE[1],
    platform: str = sys.platform,
    user32: Any = None,
) -> bool:
    """Resize the native window so its client height equals `content_px` CSS pixels.

    Keeps x, y and width fixed (moves the window up only when the new bottom would leave
    the monitor work area). Marshals inspection onto the WinForms UI thread when
    `InvokeRequired` is True and guards against disposed or uncreated handles.
    """
    if platform != "win32":
        return False
    native_form = getattr(window, "native", None)
    if native_form is None:
        return False
    if bool(getattr(native_form, "IsDisposed", False)) or not bool(
        getattr(native_form, "IsHandleCreated", True)
    ):
        return False

    def _execute() -> bool:
        if bool(getattr(native_form, "IsDisposed", False)) or not bool(
            getattr(native_form, "IsHandleCreated", True)
        ):
            return False
        import ctypes
        from ctypes import wintypes

        hwnd = _resolve_native_hwnd(native_form)
        if hwnd is None:
            return False
        target_user32 = ctypes.windll.user32 if user32 is None else user32

        class _MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        _configure_fn_signature(
            getattr(target_user32, "IsZoomed", None),
            [wintypes.HWND],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "IsIconic", None),
            [wintypes.HWND],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "IsWindowVisible", None),
            [wintypes.HWND],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "GetDpiForWindow", None),
            [wintypes.HWND],
            wintypes.UINT,
        )
        _configure_fn_signature(
            getattr(target_user32, "GetWindowRect", None),
            [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "GetClientRect", None),
            [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "MonitorFromWindow", None),
            [wintypes.HWND, wintypes.DWORD],
            wintypes.HMONITOR,
        )
        _configure_fn_signature(
            getattr(target_user32, "GetMonitorInfoW", None),
            [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "SetWindowPos", None),
            [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ],
            wintypes.BOOL,
        )

        if (
            target_user32.IsZoomed(hwnd)
            or target_user32.IsIconic(hwnd)
            or not target_user32.IsWindowVisible(hwnd)
        ):
            return False

        try:
            dpi = int(target_user32.GetDpiForWindow(hwnd)) or 96
        except Exception:
            dpi = 96
        scale = dpi / 96.0

        outer = wintypes.RECT()
        client = wintypes.RECT()
        if not target_user32.GetWindowRect(
            hwnd, ctypes.byref(outer)
        ) or not target_user32.GetClientRect(hwnd, ctypes.byref(client)):
            return False
        outer_h = outer.bottom - outer.top
        chrome_phys = outer_h - (client.bottom - client.top)
        try:
            for control in getattr(native_form, "Controls", ()):
                if control.GetType().Name == "MenuStrip" and getattr(control, "Visible", True):
                    chrome_phys += int(control.Height)
        except Exception:
            _LOGGER.debug("Menu strip height query failed.", exc_info=True)

        work_top = None
        work_bottom = None
        try:
            monitor = target_user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            if monitor and target_user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work_top, work_bottom = info.rcWork.top, info.rcWork.bottom
        except Exception:
            _LOGGER.debug("Monitor work area query failed.")
        if work_top is None or work_bottom is None:
            effective_fallback = fallback_max_h if fallback_max_h else baseline_height
            if not effective_fallback:
                return False
            work_top, work_bottom = outer.top, outer.top + int(effective_fallback * scale)

        target_logical = _compute_fit_height(
            content_px,
            chrome_phys / scale,
            min_height,
            int((work_bottom - work_top) / scale),
        )
        target_phys = int(round(target_logical * scale))
        if target_phys == outer_h:
            return True
        new_top = outer.top
        if new_top + target_phys > work_bottom:
            new_top = max(work_top, work_bottom - target_phys)
        # SWP_NOZORDER | SWP_NOACTIVATE
        return bool(
            target_user32.SetWindowPos(
                hwnd,
                0,
                outer.left,
                new_top,
                outer.right - outer.left,
                target_phys,
                0x0004 | 0x0010,
            )
        )

    if bool(getattr(native_form, "InvokeRequired", False)):
        outcome = {"ok": False}

        def _marshaled() -> None:
            outcome["ok"] = _execute()

        try:
            invoke_fn = getattr(native_form, "Invoke", None)
            if not callable(invoke_fn):
                return False
            try:
                from System import Action

                invoke_fn(Action(_marshaled))
            except ImportError:
                invoke_fn(_marshaled)
            return outcome["ok"]
        except Exception:
            _LOGGER.debug("Marshaled window fit skipped.", exc_info=True)
            return False

    try:
        return _execute()
    except Exception:
        _LOGGER.debug("Window fit skipped.", exc_info=True)
        return False


def _activate_window_foreground(window: Any, *, platform: str = sys.platform) -> bool:
    """Restaura y eleva la ventana al frente en Windows usando un HWND de 64 bits seguro."""
    if platform != "win32":
        return False
    try:
        native_form = getattr(window, "native", None)
        hwnd = _resolve_native_hwnd(native_form)
        if hwnd is None:
            return False
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        _configure_fn_signature(
            getattr(user32, "ShowWindow", None),
            [wintypes.HWND, ctypes.c_int],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(user32, "SetWindowPos", None),
            [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(user32, "SetForegroundWindow", None),
            [wintypes.HWND],
            wintypes.BOOL,
        )
        user32.ShowWindow(hwnd, 9)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        _LOGGER.debug("Native foreground activation skipped.", exc_info=True)
        return False


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
    if bool(getattr(native_form, "IsDisposed", False)) or not bool(
        getattr(native_form, "IsHandleCreated", True)
    ):
        return

    def _apply() -> None:
        if bool(getattr(native_form, "IsDisposed", False)) or not bool(
            getattr(native_form, "IsHandleCreated", True)
        ):
            return
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


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada principal de la aplicacion de escritorio."""
    args = parse_args(argv)
    ui_dir = resolve_ui_directory()
    index_path = ui_dir / "index.html"
    themes_path = ui_dir / "themes.css"
    styles_path = ui_dir / "styles.css"
    i18n_path = ui_dir / "i18n.js"
    script_path = ui_dir / "app.js"

    icon_path = resolve_icon_path()
    png_icon_path = resolve_png_icon_path()

    guard: SingleInstanceGuard | None = None
    if not args.smoke_test and not getattr(args, "multi_instance", False):
        guard = SingleInstanceGuard()
        if not guard.acquire():
            print(
                "An existing Gestor de luces instance is already running; "
                "bringing it to the foreground. "
                "(Pass --multi-instance to launch a side-by-side window.)",
                flush=True,
            )
            guard.signal_existing_instance()
            return 0

    autostart = _default_autostart()
    service, bridge = build_application(autostart=autostart)

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
                    themes_path,
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

    def _fit_window(content_px: int) -> bool:
        try:
            screens = getattr(webview, "screens", None)
            fallback = int(screens[0].height) if screens else None
            return _fit_native_window_height(window, content_px, fallback)
        except Exception:
            _LOGGER.debug("Window fit skipped.", exc_info=True)
            return False

    bridge.set_fit_window_callback(_fit_window)

    initial_theme = service.get_theme()
    initial_chrome = THEME_WINDOW_CHROME.get(initial_theme, THEME_WINDOW_CHROME[DEFAULT_THEME])

    window = webview.create_window(
        title="WiZ Architectural Lighting Console",
        url=index_path.as_uri(),
        js_api=JsApi(bridge, fit_window=_fit_window),
        width=win_width,
        height=win_height,
        x=win_x,
        y=win_y,
        min_size=(WINDOW_MIN_SIZE[0], WINDOW_MIN_SIZE[1]),
        background_color=str(initial_chrome["background_color"]),
        hidden=args.minimized,
    )

    def _sync_windows_theme_titlebar() -> None:
        """Sincroniza el atributo DWM de la barra de titulo segun el tema activo."""
        current_theme = service.get_theme()
        chrome = THEME_WINDOW_CHROME.get(current_theme, THEME_WINDOW_CHROME[DEFAULT_THEME])
        _set_windows_dark_titlebar_attribute(
            window,
            enabled=bool(chrome["dark_titlebar"]),
        )

    def show_window() -> None:
        """Restaura la ventana desde la bandeja y la trae al frente en Windows."""
        nonlocal is_window_visible
        is_window_visible = True
        window.show()
        try:
            window.restore()
        except Exception:
            _LOGGER.debug("Window restore skipped because window was not minimized.")
        _sync_windows_theme_titlebar()
        menu_sync_requested.set()
        _activate_window_foreground(window)
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
            threading.Thread(target=hide_window, name="GestorLucesHideOnClose", daemon=True).start()
            return False
        return True

    def on_minimized() -> None:
        """Cuando el usuario minimiza la ventana con [_], la enviamos a la bandeja."""
        if not is_quitting and is_window_visible:
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
        _sync_windows_theme_titlebar()
        tray.request_refresh()
        request_menu_sync()

    def _on_window_shown() -> None:
        _sync_windows_theme_titlebar()
        if is_window_visible:
            _activate_window_foreground(window)
        request_menu_sync()

    bridge.set_state_change_listener(_on_state_changed)
    window.events.shown += _on_window_shown
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
        profile_suffix = (
            f"webview-{ui_dir.parent.name}" if getattr(args, "multi_instance", False) else "webview"
        )
        webview_storage = resolve_default_data_dir() / profile_suffix
        webview_storage.mkdir(parents=True, exist_ok=True)
        print(f"Opening UI window ({win_width}x{win_height}) -> {index_path}", flush=True)
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
