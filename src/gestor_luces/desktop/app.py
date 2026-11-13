"""Ciclo de vida de la aplicacion de escritorio (ventana, bandeja y menu nativo).

Extraido de las antiguas closures de `main()` para que el punto de entrada quede como
raiz de composicion y el ciclo de vida se pueda instanciar y ejercitar por separado.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gestor_luces.adapters.platform.windows import (
    THEME_WINDOW_CHROME,
    WINDOW_MIN_SIZE,
    _activate_window_foreground,
    _compute_initial_window_geometry,
    _fit_native_window_height,
    _set_windows_dark_titlebar_attribute,
    _sync_native_menu,
    _to_webview_menus,
    show_message_box,
)
from gestor_luces.adapters.storage.json_repositories import resolve_default_data_dir
from gestor_luces.adapters.system.single_instance import SingleInstanceGuard
from gestor_luces.adapters.tray import Dispatch, TrayController, TrayView
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
from gestor_luces.application.service import LightControlService
from gestor_luces.domain.value_objects import DEFAULT_THEME
from gestor_luces.ports.autostart import AutostartManager
from gestor_luces.resources import resolve_app_version

_LOGGER = logging.getLogger(__name__)

WINDOW_TITLE = "WiZ Architectural Lighting Console"
MENU_SYNC_THREAD_NAME = "GestorLucesMenuSync"
HIDE_ON_CLOSE_THREAD_NAME = "GestorLucesHideOnClose"
HIDE_ON_MINIMIZE_THREAD_NAME = "GestorLucesHideOnMinimize"


def create_tray_view(dispatch: Dispatch) -> TrayView | None:
    """Elige la vista de bandeja: WinForms (colores explicitos) con respaldo `pystray`.

    `create_winforms_view` devuelve None (nunca lanza) cuando pythonnet/WinForms no estan
    disponibles, asi que la bandeja jamas desaparece por un fallo del CLR. Los imports son
    perezosos para no cargar `pystray` ni .NET cuando el arranque no llega a la bandeja.
    """
    from gestor_luces.adapters.tray.winforms_tray import create_winforms_view

    view = create_winforms_view(dispatch)
    if view is not None:
        return view
    _LOGGER.info("WinForms tray unavailable; using the pystray fallback view.")
    from gestor_luces.adapters.tray.pystray_tray import create_pystray_view

    return create_pystray_view(dispatch)


class DesktopApplication:
    """Estado y manejadores del ciclo de vida de la ventana nativa y la bandeja del sistema."""

    def __init__(
        self,
        *,
        service: LightControlService,
        bridge: WebviewBridge,
        index_path: Path,
        icon_path: Path,
        ui_dir: Path,
        debug: bool = False,
        minimized: bool = False,
        multi_instance: bool = False,
        guard: SingleInstanceGuard | None = None,
        autostart: AutostartManager | None = None,
        webview_module: Any = None,
    ) -> None:
        self._service = service
        self._bridge = bridge
        self._index_path = index_path
        self._icon_path = icon_path
        self._ui_dir = ui_dir
        self._debug = debug
        self._minimized = minimized
        self._multi_instance = multi_instance
        self._guard = guard
        self._autostart = autostart
        self._webview_module = webview_module

        self._webview: Any = None
        self._window: Any = None
        self._tray: TrayController | None = None
        self._initial_menu: list[AppMenu] = []
        self._window_size: tuple[int, int] = (0, 0)
        self._menu_sync_requested = threading.Event()
        self.is_window_visible = not minimized
        self.is_quitting = False

        self._menu_handlers: dict[str, Callable[[], None]] = {
            ACTION_TOGGLE_WINDOW: self.toggle_window,
            ACTION_TOGGLE_AUTOSTART: self.toggle_autostart,
            ACTION_EXIT: self.quit_app,
            ACTION_SHOW_SHORTCUTS: self.show_shortcuts,
            ACTION_SHOW_ABOUT: self.show_about,
        }

    @property
    def window(self) -> Any:
        """Ventana nativa creada por `create_window` (None antes de crearla)."""
        return self._window

    @property
    def tray(self) -> TrayController | None:
        """Controlador de bandeja creado junto con la ventana (None antes)."""
        return self._tray

    @property
    def window_size(self) -> tuple[int, int]:
        """Tamano inicial `(ancho, alto)` calculado para la ventana nativa."""
        return self._window_size

    def _resolve_webview(self) -> Any:
        if self._webview is None:
            if self._webview_module is not None:
                self._webview = self._webview_module
            else:
                import webview

                self._webview = webview
        return self._webview

    def create_window(self) -> Any:
        """Actualiza el autostart, crea la ventana nativa y cablea el ciclo de vida."""
        self._refresh_autostart_entry()
        webview = self._resolve_webview()
        win_width, win_height, win_x, win_y = _compute_initial_window_geometry(webview)
        self._window_size = (win_width, win_height)

        self._bridge.set_fit_window_callback(self.fit_window)

        initial_theme = self._service.get_theme()
        initial_chrome = THEME_WINDOW_CHROME.get(initial_theme, THEME_WINDOW_CHROME[DEFAULT_THEME])
        self._window = webview.create_window(
            title=WINDOW_TITLE,
            url=str(self._index_path),
            js_api=JsApi(self._bridge, fit_window=self.fit_window),
            width=win_width,
            height=win_height,
            x=win_x,
            y=win_y,
            min_size=(WINDOW_MIN_SIZE[0], WINDOW_MIN_SIZE[1]),
            background_color=str(initial_chrome["background_color"]),
            hidden=self._minimized,
        )
        self._tray = TrayController(
            self._bridge,
            show_window=self.show_window,
            hide_window=self.hide_window,
            quit_app=self.quit_app,
            is_window_visible=lambda: self.is_window_visible,
            notify_ui=self.notify_ui,
            view_factory=create_tray_view,
        )
        self._bridge.set_state_change_listener(self.on_state_changed)
        self._window.events.shown += self.on_window_shown
        self._window.events.closing += self.on_closing
        self._window.events.minimized += self.on_minimized
        self._window.events.closed += self.on_closed
        return self._window

    def start(self) -> None:
        """Arranca bandeja, hilos de soporte y el bucle nativo (bloqueante)."""
        webview = self._resolve_webview()
        threading.Thread(
            target=self._menu_sync_worker,
            name=MENU_SYNC_THREAD_NAME,
            daemon=True,
        ).start()
        if self._guard is not None:
            self._guard.listen(self.show_window)
        if self._tray is not None:
            self._tray.start()
        try:
            # private_mode=False + storage_path make localStorage (UI prefs, favorite scenes)
            # persist across launches; WebView2 defaults to an ephemeral profile otherwise.
            webview_storage = self._webview_storage_path()
            self._initial_menu = self.current_menu_spec()
            webview.start(
                http_server=True,
                debug=self._debug,
                private_mode=False,
                storage_path=str(webview_storage),
                menu=_to_webview_menus(self._initial_menu, self.on_menu_action),
                icon=str(self._icon_path) if self._icon_path.is_file() else None,
            )
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Libera la instancia unica, la bandeja y el bucle asincrono del puente."""
        if self._guard is not None:
            self._guard.release()
        if self._tray is not None:
            self._tray.stop()
        self._bridge.shutdown()

    def _webview_storage_path(self) -> Path:
        """Perfil WebView2 persistente (aislado cuando se corre en modo multi-instancia)."""
        profile_suffix = "webview"
        if self._multi_instance:
            profile_suffix = f"webview-{self._ui_dir.parent.name}"
        webview_storage = resolve_default_data_dir() / profile_suffix
        webview_storage.mkdir(parents=True, exist_ok=True)
        return webview_storage

    def _refresh_autostart_entry(self) -> None:
        """Keep a portable build's autostart entry pointing at the current location."""
        try:
            if self._autostart is not None and self._autostart.refresh_if_stale():
                _LOGGER.info("Autostart entry was stale and has been refreshed.")
        # `WindowsRegistryAutostart` solo falla con winreg, es decir con `OSError`; una
        # entrada de autostart obsoleta no puede impedir que la consola arranque.
        except OSError:
            _LOGGER.exception("Autostart refresh failed.")

    def fit_window(self, content_px: int) -> bool:
        """Ajusta la altura nativa de la ventana para que el alto util coincida con el de la UI."""
        try:
            screens = getattr(self._webview, "screens", None)
            fallback = int(screens[0].height) if screens else None
            resized = _fit_native_window_height(self._window, content_px, fallback)
            # Una linea por ajuste pedido: si la medicion oscila, el log lo muestra.
            _LOGGER.info("Window fit requested: content=%spx applied=%s", content_px, resized)
            return resized
        # FRONTERA: el ajuste cruza a pywebview (`screens`) y a pythonnet/WinForms; el CLR
        # no garantiza el tipo de excepcion. Un fallo del host devuelve `False` y la UI
        # conserva el tamano actual en vez de romper el hilo que pidio el ajuste.
        except Exception:
            _LOGGER.debug("Window fit skipped.", exc_info=True)
            return False

    def sync_theme_titlebar(self) -> None:
        """Sincroniza el atributo DWM de la barra de titulo segun el tema activo."""
        current_theme = self._service.get_theme()
        chrome = THEME_WINDOW_CHROME.get(current_theme, THEME_WINDOW_CHROME[DEFAULT_THEME])
        _set_windows_dark_titlebar_attribute(
            self._window,
            enabled=bool(chrome["dark_titlebar"]),
        )

    def show_window(self) -> None:
        """Restaura la ventana desde la bandeja y la trae al frente en Windows."""
        self.is_window_visible = True
        self._window.show()
        try:
            self._window.restore()
        # FRONTERA: `restore` se marshalea a WinForms con pythonnet, que puede rechazar el
        # handle nativo cuando la ventana no estaba minimizada. Mostrar la ventana ya
        # ocurrio, asi que el resultado deseado se mantiene.
        except Exception:
            _LOGGER.debug("Window restore skipped because window was not minimized.", exc_info=True)
        self.sync_theme_titlebar()
        self.request_menu_sync()
        _activate_window_foreground(self._window)
        if self._tray is not None:
            self._tray.request_refresh()

    def hide_window(self) -> None:
        """Oculta la ventana en la bandeja manteniendo vivos el bucle UDP y los temporizadores."""
        self.is_window_visible = False
        self._window.hide()
        self.request_menu_sync()
        if self._tray is not None:
            self._tray.request_refresh()

    def notify_ui(self) -> None:
        """Avisa a la vista web que una accion de la bandeja modifico el estado luminico."""
        if not self.is_window_visible or self.is_quitting:
            return
        self._evaluate_js_quietly(
            "window.onTrayStateChanged && window.onTrayStateChanged()",
            "tray state notification",
        )

    def _evaluate_js_quietly(self, script: str, context: str) -> None:
        """Ejecuta JavaScript en la vista sin dejar que un fallo del webview propague.

        FRONTERA: `evaluate_js` corre sobre pythonnet/WebView2, que puede fallar mientras la
        vista no esta lista, esta navegando o ya se cerro. Ambos usos son notificaciones
        accesorias (aviso de la bandeja y dialogo de atajos), asi que se registra la traza y
        la accion nativa que las origino sigue su curso.
        """
        try:
            self._window.evaluate_js(script)
        # FRONTERA (ver el docstring): el fallo de la vista no revierte la accion nativa.
        except Exception:
            _LOGGER.debug("Skipped UI notification (%s).", context, exc_info=True)

    def quit_app(self) -> None:
        """Autoriza el cierre definitivo y destruye la ventana nativa.

        La bandeja y el bucle del puente no se liberan aca: `quit_app` corre en el hilo
        de acciones de la bandeja, y detener el icono desde ese hilo mientras pystray
        reaplica el menu deja el proceso a medio cerrar. Al destruir la ventana,
        `webview.start()` retorna y `cleanup()` libera todo en el orden correcto.
        """
        self.is_quitting = True
        try:
            self._window.destroy()
            return
        # FRONTERA: `destroy` se marshalea a WinForms con pythonnet durante el cierre. Si
        # falla, la liberacion de bandeja y bucle asincrono debe ocurrir igual, asi que se
        # cae explicitamente a `cleanup()`.
        except Exception:
            _LOGGER.exception("Window destroy failed while quitting; releasing resources.")
        self.cleanup()

    def on_closing(self) -> bool:
        """Intercepta el boton [X] para minimizar a la bandeja salvo cuando se invoca Quit.

        Importante en WinForms/pywebview: `window.events.closing` se ejecuta de forma
        sincrona en el hilo principal de la ventana (`should_lock=True`). Llamar a
        `window.hide()` directamente dentro de `FormClosing` puede reentrar o bloquear
        con `self.Invoke(self.Hide)`. Por eso despachamos `hide_window` en un hilo corto
        apenas `on_closing` devuelve `False` (`args.Cancel = True`).
        """
        if not self.is_quitting:
            threading.Thread(
                target=self.hide_window,
                name=HIDE_ON_CLOSE_THREAD_NAME,
                daemon=True,
            ).start()
            return False
        return True

    def on_minimized(self) -> None:
        """Cuando el usuario minimiza la ventana con [_], la enviamos a la bandeja."""
        if not self.is_quitting and self.is_window_visible:
            threading.Thread(
                target=self.hide_window,
                name=HIDE_ON_MINIMIZE_THREAD_NAME,
                daemon=True,
            ).start()

    def on_closed(self) -> None:
        """Garantiza la liberacion de recursos si el sistema operativo cierra la ventana."""
        if self._tray is not None:
            self._tray.stop()
        self._bridge.shutdown()

    def current_menu_spec(self) -> list[AppMenu]:
        """Construye el modelo de menu nativo a partir del estado actual del puente."""
        snapshot = self._bridge.get_tray_snapshot()
        return build_app_menu(
            language=str(snapshot.get("language") or "en"),
            window_visible=self.is_window_visible,
            autostart_enabled=bool(self._bridge.get_autostart().get("enabled")),
        )

    def _menu_sync_worker(self) -> None:
        """Serialize menu updates off the GUI and bridge-loop threads."""
        while not self.is_quitting:
            self._menu_sync_requested.wait()
            self._menu_sync_requested.clear()
            if self.is_quitting:
                break
            try:
                _sync_native_menu(self._window, self.current_menu_spec())
            # FRONTERA: este es el bucle que serializa los refrescos del menu nativo y cruza
            # a WinForms con pythonnet; una reaplicacion fallida no puede matar el unico
            # hilo que reaplica el menu hasta el cierre.
            except Exception:
                _LOGGER.debug("Menu refresh skipped.", exc_info=True)

    def request_menu_sync(self) -> None:
        """Solicita al hilo serializador que reaplique el menu nativo."""
        self._menu_sync_requested.set()

    def toggle_window(self) -> None:
        """Alterna entre mostrar y ocultar la ventana segun el estado real."""
        if self.is_window_visible:
            self.hide_window()
        else:
            self.show_window()

    def show_shortcuts(self) -> None:
        """Muestra la ventana y abre el dialogo de atajos de la UI."""
        self.show_window()
        self._evaluate_js_quietly(
            "(function(){var d=document.getElementById('shortcuts-dialog');"
            "if(d&&!d.open){d.showModal();}})()",
            "shortcuts dialog",
        )

    def show_about(self) -> None:
        """Muestra el cuadro nativo 'Acerca de' con la version y la licencia."""
        language = str(self._bridge.get_tray_snapshot().get("language") or "en")
        text = build_about_text(language, resolve_app_version())
        show_message_box(text, APP_DISPLAY_NAME)

    def toggle_autostart(self) -> None:
        """Alterna el inicio con Windows y sincroniza el menu nativo."""
        current = bool(self._bridge.get_autostart().get("enabled"))
        result = self._bridge.set_autostart(not current)
        if not result.get("ok"):
            _LOGGER.warning("Autostart toggle failed: %s", result.get("error"))
        self.request_menu_sync()

    def on_menu_action(self, action_id: str) -> None:
        """Despacha una accion del menu nativo y reaplica el menu salvo al salir."""
        handler = self._menu_handlers.get(action_id)
        if handler is None:
            _LOGGER.warning("Unknown menu action: %s", action_id)
            return
        try:
            handler()
        # FRONTERA: esto corre dentro del callback de accion de la bandeja nativa; una
        # accion fallida (ventana, registro o dialogo nativo) no debe propagarse al CLR que
        # despacha el menu, y el refresco posterior mantiene el menu coherente.
        except Exception:
            _LOGGER.exception("Menu action '%s' failed.", action_id)
        if action_id != ACTION_EXIT:
            self.request_menu_sync()

    def on_state_changed(self) -> None:
        """Reacciona a una mutacion hecha desde la UI: titulo, bandeja y menu."""
        self.sync_theme_titlebar()
        if self._tray is not None:
            self._tray.request_refresh()
        self.request_menu_sync()

    def on_window_shown(self) -> None:
        """Sincroniza el cromado nativo y el menu cuando la ventana vuelve a mostrarse."""
        self.sync_theme_titlebar()
        if self.is_window_visible:
            _activate_window_foreground(self._window)
        self.request_menu_sync()
