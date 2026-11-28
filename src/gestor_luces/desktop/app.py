"""Ciclo de vida de la aplicacion de escritorio (ventana, bandeja y menu nativo).

Extraido de las antiguas closures de `main()` para que el punto de entrada quede como
raiz de composicion y el ciclo de vida se pueda instanciar y ejercitar por separado.
"""

from __future__ import annotations

import logging
import threading
import uuid
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
    _sync_native_menu_theme,
    _to_webview_menus,
    apply_window_icon,
    show_message_box,
    window_chrome,
)
from gestor_luces.adapters.platform.windows.window_geometry import (
    _extract_screen_area,
    _select_primary_screen,
)
from gestor_luces.adapters.storage.json_repositories import resolve_default_data_dir
from gestor_luces.adapters.system.single_instance import SingleInstanceGuard
from gestor_luces.adapters.tray import Dispatch, TrayController, TrayView
from gestor_luces.adapters.tray.menu_model import build_tray_hint
from gestor_luces.adapters.ui_webview.app_menu import (
    ACTION_EXIT,
    ACTION_SHOW_ABOUT,
    ACTION_SHOW_SHORTCUTS,
    ACTION_TOGGLE_AUTOSTART,
    ACTION_TOGGLE_WINDOW,
    APP_LICENSE,
    AppMenu,
    build_about_text,
    build_about_title,
    build_app_menu,
    build_window_title,
)
from gestor_luces.adapters.ui_webview.bridge import (
    BlockedJsApi,
    JsApi,
    WebviewBridge,
    build_exposed_functions,
)
from gestor_luces.adapters.ui_webview.http_server import NoCacheBottleServer
from gestor_luces.domain.value_objects import DEFAULT_THEME, normalize_language, normalize_theme
from gestor_luces.ports.autostart import AutostartManager
from gestor_luces.ports.light_control import LightControlServicePort
from gestor_luces.resources import resolve_app_version

_LOGGER = logging.getLogger(__name__)

WINDOW_TITLE = "WiZ Architectural Lighting Console"
MENU_SYNC_THREAD_NAME = "WizConsoleMenuSync"
HIDE_ON_CLOSE_THREAD_NAME = "WizConsoleHideOnClose"
HIDE_ON_MINIMIZE_THREAD_NAME = "WizConsoleHideOnMinimize"


def _build_initial_ui_url(
    index_path: Path,
    theme: str,
    *,
    language: str | None = None,
    cache_bust: str | None = None,
) -> str:
    """Construye la URL inicial de la vista web con query anti-cache y fragmento de tema/idioma."""
    normalized = normalize_theme(theme)
    query = f"?v={cache_bust}" if cache_bust else ""
    if language is None:
        return f"{index_path}{query}#theme={normalized}"
    normalized_lang = normalize_language(language)
    return f"{index_path}{query}#theme={normalized}&lang={normalized_lang}"


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
        service: LightControlServicePort,
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
        self._window_size: tuple[int, int] = (0, 0)
        self._state_lock = threading.Lock()
        self._menu_sync_cond = threading.Condition(self._state_lock)
        self._menu_sync_pending = False
        self._menu_sync_thread: threading.Thread | None = None
        self._is_window_visible = not minimized
        self._is_quitting = False
        self._visibility_generation = 0
        self._last_titlebar_theme: str | None = None
        self._last_menu_language = str(service.get_language() or "en")
        tray_hint_getter = getattr(service, "get_tray_hint_seen", None)
        self._tray_hint_shown = bool(tray_hint_getter()) if callable(tray_hint_getter) else False

        self._menu_handlers: dict[str, Callable[[], None]] = {
            ACTION_TOGGLE_WINDOW: self.toggle_window,
            ACTION_TOGGLE_AUTOSTART: self.toggle_autostart,
            ACTION_EXIT: self.quit_app,
            ACTION_SHOW_SHORTCUTS: self.show_shortcuts,
            ACTION_SHOW_ABOUT: self.show_about,
        }

    @property
    def is_window_visible(self) -> bool:
        """Indica si la ventana principal esta visible fuera de la bandeja."""
        with self._state_lock:
            return self._is_window_visible

    @is_window_visible.setter
    def is_window_visible(self, value: bool) -> None:
        with self._state_lock:
            self._is_window_visible = bool(value)

    @property
    def is_quitting(self) -> bool:
        """Indica si la aplicacion ya inicio su secuencia de cierre definitivo."""
        with self._state_lock:
            return self._is_quitting

    @is_quitting.setter
    def is_quitting(self, value: bool) -> None:
        with self._menu_sync_cond:
            self._is_quitting = bool(value)
            if self._is_quitting:
                self._menu_sync_cond.notify_all()

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

        initial_theme = normalize_theme(self._service.get_theme())
        initial_language = normalize_language(self._service.get_language())
        initial_chrome = THEME_WINDOW_CHROME.get(initial_theme, THEME_WINDOW_CHROME[DEFAULT_THEME])
        js_api = JsApi(self._bridge, fit_window=self.fit_window)
        self._window = webview.create_window(
            title=build_window_title(initial_language),
            url=_build_initial_ui_url(
                self._index_path,
                initial_theme,
                language=initial_language,
                cache_bust=uuid.uuid4().hex[:8],
            ),
            js_api=BlockedJsApi(),
            width=win_width,
            height=win_height,
            x=win_x,
            y=win_y,
            min_size=(
                min(WINDOW_MIN_SIZE[0], win_width),
                min(WINDOW_MIN_SIZE[1], win_height),
            ),
            background_color=str(initial_chrome["background_color"]),
            hidden=self._minimized,
        )
        self._window.expose(*build_exposed_functions(js_api))
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
        self._menu_sync_thread = threading.Thread(
            target=self._menu_sync_worker,
            name=MENU_SYNC_THREAD_NAME,
            daemon=True,
        )
        self._menu_sync_thread.start()
        if self._guard is not None:
            self._guard.listen(self.show_window)
        if self._tray is not None:
            self._tray.start()
        try:
            # private_mode=False + storage_path make localStorage (UI prefs, favorite scenes)
            # persist across launches; WebView2 defaults to an ephemeral profile otherwise.
            webview_storage = self._webview_storage_path()
            initial_menu = self.current_menu_spec()
            webview.start(
                http_server=True,
                server=NoCacheBottleServer,
                debug=self._debug,
                private_mode=False,
                storage_path=str(webview_storage),
                menu=_to_webview_menus(initial_menu, self.on_menu_action),
                icon=str(self._icon_path) if self._icon_path.is_file() else None,
            )
        finally:
            self.cleanup()

    def _release_window_icons(self) -> None:
        """Libera los HICON cacheados para la ventana nativa cuando la capa Win32 los expone."""
        if self._window is None:
            return
        release_fn = getattr(window_chrome, "release_window_icons", None)
        if callable(release_fn):
            release_fn(self._window)

    def cleanup(self) -> None:
        """Libera la instancia unica, la bandeja y el bucle asincrono del puente."""
        # El hilo que reaplica el menu nativo queda aparcado en su Condition: marcarlo como
        # cierre y despertarlo es lo que lo saca del wait y lo hace salir del bucle. Sin
        # esto sobrevive al cierre y solo muere porque es demonio.
        with self._menu_sync_cond:
            self._is_quitting = True
            self._menu_sync_cond.notify_all()
        self._release_window_icons()
        if self._guard is not None:
            self._guard.release()
        if self._tray is not None:
            self._tray.stop()
        self._bridge.shutdown()
        menu_thread = self._menu_sync_thread
        if (
            menu_thread is not None
            and menu_thread.is_alive()
            and threading.current_thread() is not menu_thread
        ):
            menu_thread.join(timeout=1.0)

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
            primary = _select_primary_screen(screens) if screens else None
            area = _extract_screen_area(primary) if primary is not None else None
            fallback = area[3] if area is not None else None
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

    def sync_theme_titlebar(self, *, force: bool = False) -> None:
        """Sincroniza el atributo DWM de la barra de titulo y el MenuStrip segun el tema activo."""
        if self._window is None:
            return
        current_theme = normalize_theme(self._service.get_theme())
        with self._state_lock:
            if not force and self._last_titlebar_theme == current_theme:
                return
        chrome = THEME_WINDOW_CHROME.get(current_theme, THEME_WINDOW_CHROME[DEFAULT_THEME])
        applied = _set_windows_dark_titlebar_attribute(
            self._window,
            enabled=bool(chrome["dark_titlebar"]),
        )
        _sync_native_menu_theme(self._window, current_theme)
        if applied:
            with self._state_lock:
                self._last_titlebar_theme = current_theme

    def sync_window_title(self, language: str | None = None) -> None:
        """Update the native window title to match the active language when supported."""
        if self._window is None:
            return
        resolved_lang = normalize_language(
            language if language is not None else self._service.get_language()
        )
        set_title_fn = getattr(self._window, "set_title", None)
        if not callable(set_title_fn):
            return
        try:
            set_title_fn(build_window_title(resolved_lang))
        except Exception:
            _LOGGER.debug("Window title update skipped.", exc_info=True)

    def show_window(self) -> None:
        """Restaura la ventana desde la bandeja y la trae al frente en Windows."""
        with self._state_lock:
            if self._is_quitting or self._window is None:
                return
            self._is_window_visible = True
            self._visibility_generation += 1
        self._window.show()
        try:
            self._window.restore()
        # FRONTERA: `restore` se marshalea a WinForms con pythonnet, que puede rechazar el
        # handle nativo cuando la ventana no estaba minimizada. Mostrar la ventana ya
        # ocurrio, asi que el resultado deseado se mantiene.
        except Exception:
            _LOGGER.debug("Window restore skipped because window was not minimized.", exc_info=True)
        self.sync_theme_titlebar(force=True)
        self.request_menu_sync()
        _activate_window_foreground(self._window)
        if self._tray is not None:
            self._tray.request_refresh()

    def _maybe_show_tray_hint(self) -> None:
        """Show the non-intrusive hide-to-tray notice at most once and persist the flag."""
        with self._state_lock:
            if self._tray_hint_shown or self._is_quitting:
                return
        tray = self._tray
        if tray is None:
            return
        lang = normalize_language(str(self._service.get_language() or "en"))
        title, message = build_tray_hint(lang)
        if tray.show_notification(title, message):
            with self._state_lock:
                self._tray_hint_shown = True
            setter = getattr(self._service, "set_tray_hint_seen", None)
            if callable(setter):
                try:
                    setter(True)
                except Exception:
                    _LOGGER.debug("Could not persist tray_hint_seen flag.", exc_info=True)

    def _apply_hide(self, *, show_tray_hint: bool = False) -> None:
        """Ejecuta el ocultamiento nativo y notifica menu y bandeja."""
        self._window.hide()
        self.request_menu_sync()
        if self._tray is not None:
            self._tray.request_refresh()
        if show_tray_hint:
            self._maybe_show_tray_hint()

    def hide_window(self) -> None:
        """Oculta la ventana en la bandeja manteniendo vivos el bucle UDP y los temporizadores."""
        with self._state_lock:
            if self._is_quitting or self._window is None:
                return
            self._is_window_visible = False
            self._visibility_generation += 1
        self._apply_hide()

    def _hide_if_generation(
        self,
        generation: int,
        *,
        show_tray_hint: bool = False,
    ) -> None:
        """Oculta la ventana solo si ninguna transicion posterior invalido la solicitud."""
        with self._state_lock:
            if (
                self._is_quitting
                or self._window is None
                or self._visibility_generation != generation
            ):
                return
            self._is_window_visible = False
            self._visibility_generation += 1
        self._apply_hide(show_tray_hint=show_tray_hint)

    def notify_ui(self) -> None:
        """Avisa a la vista web que una accion de la bandeja modifico el estado luminico."""
        with self._state_lock:
            visible = self._is_window_visible
            quitting = self._is_quitting
        if not visible or quitting:
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
        with self._menu_sync_cond:
            self._is_quitting = True
            self._menu_sync_cond.notify_all()
        if self._window is not None:
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
        with self._state_lock:
            if self._is_quitting:
                return True
            generation = self._visibility_generation
        threading.Thread(
            target=lambda: self._hide_if_generation(generation, show_tray_hint=True),
            name=HIDE_ON_CLOSE_THREAD_NAME,
            daemon=True,
        ).start()
        return False

    def on_minimized(self) -> None:
        """Cuando el usuario minimiza la ventana con [_], la enviamos a la bandeja."""
        with self._state_lock:
            if self._is_quitting or not self._is_window_visible:
                return
            generation = self._visibility_generation
        threading.Thread(
            target=lambda: self._hide_if_generation(generation, show_tray_hint=True),
            name=HIDE_ON_MINIMIZE_THREAD_NAME,
            daemon=True,
        ).start()

    def on_closed(self) -> None:
        """Garantiza la liberacion de recursos si el sistema operativo cierra la ventana."""
        with self._menu_sync_cond:
            self._is_quitting = True
            self._menu_sync_cond.notify_all()
        self._release_window_icons()
        if self._tray is not None:
            self._tray.stop()
        self._bridge.shutdown()

    def current_menu_spec(self) -> list[AppMenu]:
        """Construye el modelo de menu nativo a partir del estado actual del puente."""
        snapshot = self._bridge.get_tray_snapshot()
        language = str(snapshot.get("language") or "en")
        with self._state_lock:
            self._last_menu_language = language
            visible = self._is_window_visible
        return build_app_menu(
            language=language,
            window_visible=visible,
            autostart_enabled=bool(self._bridge.get_autostart().get("enabled")),
        )

    def _menu_sync_worker(self) -> None:
        """Serialize menu updates off the GUI and bridge-loop threads."""
        while True:
            with self._menu_sync_cond:
                while not self._menu_sync_pending and not self._is_quitting:
                    self._menu_sync_cond.wait()
                if self._is_quitting:
                    break
                self._menu_sync_pending = False
            try:
                _sync_native_menu(self._window, self.current_menu_spec())
                _sync_native_menu_theme(self._window, normalize_theme(self._service.get_theme()))
            # FRONTERA: este es el bucle que serializa los refrescos del menu nativo y cruza
            # a WinForms con pythonnet; una reaplicacion fallida no puede matar el unico
            # hilo que reaplica el menu hasta el cierre.
            except Exception:
                _LOGGER.debug("Menu refresh skipped.", exc_info=True)

    def request_menu_sync(self) -> None:
        """Solicita al hilo serializador que reaplique el menu nativo."""
        with self._menu_sync_cond:
            self._menu_sync_pending = True
            self._menu_sync_cond.notify()

    def toggle_window(self) -> None:
        """Alterna entre mostrar y ocultar la ventana segun el estado real."""
        with self._state_lock:
            if self._is_quitting:
                return
            visible = self._is_window_visible
        if visible:
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
        """Muestra el cuadro nativo 'Acerca de' con los metadatos del paquete."""
        language = str(self._bridge.get_tray_snapshot().get("language") or "en")
        text = build_about_text(language, resolve_app_version(), APP_LICENSE)
        show_message_box(text, build_about_title(language))

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
        """Reacciona a una mutacion hecha desde la UI: titulo, bandeja y menu si cambio idioma."""
        self.sync_theme_titlebar()
        if self._tray is not None:
            self._tray.request_refresh()
        current_language = str(self._service.get_language() or "en")
        with self._state_lock:
            language_changed = current_language != self._last_menu_language
            if language_changed:
                self._last_menu_language = current_language
        if language_changed:
            self.sync_window_title(current_language)
            self.request_menu_sync()

    def on_window_shown(self) -> None:
        """Sincroniza el cromado nativo y el menu cuando la ventana vuelve a mostrarse."""
        self.sync_theme_titlebar(force=True)
        # La barra de tareas y alt+tab piden el icono a la ventana: se fija en cada muestra
        # (es idempotente) para no depender del orden interno de pywebview.
        apply_window_icon(self._window, self._icon_path)
        if self.is_window_visible:
            _activate_window_foreground(self._window)
        self.request_menu_sync()
