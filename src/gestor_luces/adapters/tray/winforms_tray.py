"""Vista de bandeja nativa con `System.Windows.Forms.NotifyIcon` y `ContextMenuStrip`.

Motivo (T-3.8): el menu clasico de `pystray` comparte la clase de ventana registrada con
`hbrBackground = COLOR_WINDOW + 1`, asi que siempre se pinta con el fondo blanco del
sistema y el texto del tema oscuro queda ilegible («fondo blanco, letras blancas
pareciera, mucho brillo»). Un `ContextMenuStrip` no depende de esa clase de ventana: los
colores son explicitos, los submenus se despliegan al pasar el cursor (`DropDownItems`,
sin hacks de clic) y actualizar el menu no destruye ningun `HMENU` mientras esta abierto.

Restriccion verificada del entorno (pythonnet 3.2.1 sobre .NET Framework 4.8): pythonnet
no emite tipos derivados en esta configuracion, asi que las subclases de
`ProfessionalColorTable`/`ToolStripRenderer` no reciben despacho virtual desde .NET y la
paleta no se puede inyectar por una tabla de colores. Por eso el tema se aplica con
colores por control (`BackColor`/`ForeColor`), `RenderMode = System` y un punto de color
generado como `Image` para marcar el nivel activo: el glifo de check nativo tiene color
fijo y desaparece sobre el tema oscuro.

`pythonnet` se importa dentro de `_load_winforms()` (nunca al importar el modulo) para que
el paquete se pueda usar en Linux/CI sin CLR y para que la vista degradada a `pystray`
sea siempre posible.
"""

from __future__ import annotations

import ctypes
import io
import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from gestor_luces.adapters.tray.menu_model import TrayMenuEntry
from gestor_luces.adapters.tray.tray_view import (
    ICON_NAME,
    Dispatch,
    TrayView,
    log_applied_menu,
    render_icon_image,
    resolve_entry_action,
)

_LOGGER = logging.getLogger(__name__)

#: `NotifyIcon.Text` admite 63 caracteres; un texto mas largo lanza una excepcion.
NOTIFY_TEXT_LIMIT = 63
_COINIT_APARTMENTTHREADED = 0x2
#: Tamano por defecto de `ToolStrip.ImageScalingSize`, para el punto del nivel activo.
CHECK_DOT_SIZE = 16

DestroyIcon = Callable[[int], None]

#: Estado deseado: modelo de menu, tooltip, color del icono y tema activo.
State = tuple[list[TrayMenuEntry], str, tuple[int, int, int], str]


@dataclass(frozen=True)
class TrayPalette:
    """Colores explicitos del menu de bandeja, independientes del tema de Windows."""

    background: str
    text: str
    disabled_text: str
    selection: str


LIGHT_PALETTE = TrayPalette(
    background="#F7F5F2",
    text="#1C1C1F",
    disabled_text="#8A8A8E",
    selection="#E4DED6",
)
DARK_PALETTE = TrayPalette(
    background="#1B1B1F",
    text="#E6E6EA",
    disabled_text="#7A7A82",
    selection="#2A2A31",
)
DEFAULT_PALETTE = LIGHT_PALETTE

THEME_PALETTES: dict[str, TrayPalette] = {
    "architectural-stone": LIGHT_PALETTE,
    "atmospheric-dark": DARK_PALETTE,
}


def resolve_palette(theme: str | None) -> TrayPalette:
    """Paleta del tema activo; cualquier tema desconocido cae en la paleta clara."""
    return THEME_PALETTES.get(str(theme or "").strip().lower(), DEFAULT_PALETTE)


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """Convierte un color `#RRGGBB` en una tupla RGB (validada, sin depender de .NET)."""
    text = str(value).strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"Not a #RRGGBB color: {value!r}")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


class _WinFormsApi:
    """Modulos de .NET resueltos una sola vez (import perezoso y guardado)."""

    def __init__(self, forms: Any, drawing: Any, action: Any, memory_stream: Any) -> None:
        self.forms = forms
        self.drawing = drawing
        self.action = action
        self.memory_stream = memory_stream


_API: _WinFormsApi | None = None
_API_RESOLVED = False


def _load_winforms() -> _WinFormsApi | None:
    """Resuelve pythonnet y WinForms una sola vez; devuelve None si no estan disponibles.

    Es el unico punto de import de .NET en el modulo, y nunca lanza: cualquier fallo se
    traduce en `None` para que la bandeja caiga a la vista de `pystray`.
    """
    global _API, _API_RESOLVED
    if _API_RESOLVED:
        return _API
    _API_RESOLVED = True
    try:
        import clr

        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        import System.Drawing as drawing
        import System.Windows.Forms as forms
        from System import Action
        from System.IO import MemoryStream
    except Exception:
        _LOGGER.debug("WinForms is unavailable; the tray falls back to pystray.", exc_info=True)
        return None
    _API = _WinFormsApi(forms=forms, drawing=drawing, action=Action, memory_stream=MemoryStream)
    return _API


def _color(value: str, api: _WinFormsApi) -> Any:
    """Convierte un color de la paleta en un `System.Drawing.Color`."""
    return api.drawing.Color.FromArgb(*parse_hex_color(value))


def _dot_image(palette: TrayPalette, api: _WinFormsApi) -> Any:
    """Punto de color con el que se marca el nivel activo del grupo radio.

    El glifo de check nativo se dibuja con un color fijo del sistema, invisible sobre el
    fondo oscuro; una imagen propia si respeta la paleta.
    """
    size = CHECK_DOT_SIZE
    bitmap = api.drawing.Bitmap(size, size)
    graphics = api.drawing.Graphics.FromImage(bitmap)
    brush = api.drawing.SolidBrush(_color(palette.text, api))
    try:
        try:
            from System.Drawing.Drawing2D import SmoothingMode

            graphics.SmoothingMode = SmoothingMode.AntiAlias
        except Exception:
            _LOGGER.debug("Anti-aliasing unavailable for the tray check dot.", exc_info=True)
        inset = size // 4
        graphics.FillEllipse(brush, inset, inset, size - 2 * inset, size - 2 * inset)
    finally:
        brush.Dispose()
        graphics.Dispose()
    return bitmap


def _click_handler(dispatch: Dispatch, action_id: str, payload: Any) -> Callable[..., None]:
    """Handler de clic de una hoja: entrega la accion al controlador de bandeja."""

    def _on_click(sender: Any, event_args: Any) -> None:
        dispatch(action_id, payload)

    return _on_click


def _build_menu_items(
    spec: Sequence[TrayMenuEntry],
    palette: TrayPalette,
    dispatch: Dispatch,
    *,
    api: _WinFormsApi | None = None,
    check_image: Any = None,
) -> list[Any]:
    """Traduce el modelo puro a items reales de WinForms con la paleta aplicada.

    Es pura respecto del icono: no crea la ventana ni toca el `NotifyIcon`, solo objetos
    `ToolStripMenuItem`/`ToolStripSeparator`, de modo que las pruebas pueden verificar el
    arbol y los colores sin escritorio.
    """
    resolved = api or _load_winforms()
    if resolved is None:
        raise RuntimeError("WinForms is not available in this environment")
    image = check_image
    if image is None and _needs_check_dot(spec):
        image = _dot_image(palette, resolved)
    return [
        _build_menu_item(
            entry,
            palette,
            dispatch,
            resolved,
            image,
            background=palette.background,
        )
        for entry in spec
    ]


def _needs_check_dot(entries: Sequence[TrayMenuEntry]) -> bool:
    """Indica si el modelo tiene algun item marcado que necesite el punto de color."""
    for entry in entries:
        if entry.checked:
            return True
        if entry.children and _needs_check_dot(entry.children):
            return True
    return False


def _build_menu_item(
    entry: TrayMenuEntry,
    palette: TrayPalette,
    dispatch: Dispatch,
    api: _WinFormsApi,
    check_image: Any,
    *,
    background: str,
) -> Any:
    """Construye un item (hoja, padre de submenu o separador) con sus colores."""
    if entry.is_separator:
        return api.forms.ToolStripSeparator()
    item = api.forms.ToolStripMenuItem(entry.label)
    item.BackColor = _color(background, api)
    item.ForeColor = _color(palette.text if entry.enabled else palette.disabled_text, api)
    item.Enabled = entry.enabled
    item.CheckOnClick = False
    if entry.checked is not None:
        item.Checked = bool(entry.checked)
        if entry.checked and check_image is not None:
            item.Image = check_image
    if entry.children:
        # Submenu real: WinForms lo despliega al pasar el cursor. No hay handler de clic en
        # el padre (un clic no debe abrir ni cerrar nada a mano).
        dropdown = item.DropDown
        dropdown.BackColor = _color(palette.selection, api)
        dropdown.ForeColor = _color(palette.text, api)
        dropdown.ShowCheckMargin = False
        for child in entry.children:
            dropdown.Items.Add(
                _build_menu_item(
                    child,
                    palette,
                    dispatch,
                    api,
                    check_image,
                    background=palette.selection,
                )
            )
        return item
    target = resolve_entry_action(entry)
    if target is not None and entry.enabled:
        action_id, payload = target
        item.Click += _click_handler(dispatch, action_id, payload)
    return item


def _destroy_icon_handle(handle: int) -> None:
    """Libera un `HICON` creado con `Bitmap.GetHicon()` (Windows no lo libera solo)."""
    try:
        ctypes.windll.user32.DestroyIcon(handle)
    except Exception:
        _LOGGER.debug("DestroyIcon failed for handle %s.", handle, exc_info=True)


def _co_initialize_apartment() -> None:
    """Inicializa el hilo de la vista como STA, requisito de COM/WinForms."""
    try:
        ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    except Exception:
        _LOGGER.debug("STA initialization failed; continuing.", exc_info=True)


def _build_icon_image(rgb: tuple[int, int, int], api: _WinFormsApi) -> tuple[Any, int]:
    """Convierte la imagen PIL en un `Icon` de WinForms a traves de un flujo en memoria."""
    buffer = io.BytesIO()
    render_icon_image(rgb).save(buffer, format="PNG")
    stream = api.memory_stream(buffer.getvalue())
    source = api.drawing.Image.FromStream(stream)
    bitmap = api.drawing.Bitmap(source)
    try:
        handle = bitmap.GetHicon()
        return api.drawing.Icon.FromHandle(handle), int(handle.ToInt64())
    finally:
        bitmap.Dispose()
        source.Dispose()
        stream.Dispose()


def _signature(state: State) -> tuple[Any, ...]:
    """Huella del estado aplicado, para descartar reaplicaciones identicas."""
    spec, title, rgb, theme = state
    return (tuple(spec), title, tuple(rgb), theme)


def create_winforms_view(
    dispatch: Dispatch,
    *,
    destroy_icon: DestroyIcon | None = None,
    api: _WinFormsApi | None = None,
) -> TrayView | None:
    """Crea la vista WinForms, o `None` si pythonnet/WinForms no estan disponibles.

    Nunca lanza: la bandeja debe seguir existiendo aunque el CLR no cargue, y con ella el
    respaldo de `pystray`.
    """
    resolved = api or _load_winforms()
    if resolved is None:
        return None
    try:
        return WinFormsTrayView(dispatch, api=resolved, destroy_icon=destroy_icon)
    except Exception:
        _LOGGER.exception("WinForms tray view could not be created; falling back to pystray.")
        return None


class WinFormsTrayView:
    """Vista de bandeja con `NotifyIcon` y `ContextMenuStrip` propios."""

    def __init__(
        self,
        dispatch: Dispatch,
        *,
        api: _WinFormsApi,
        destroy_icon: DestroyIcon | None = None,
    ) -> None:
        self._dispatch = dispatch
        self._api = api
        self._destroy_icon = destroy_icon or _destroy_icon_handle
        self._lock = threading.Lock()
        self._form: Any = None
        self._notify: Any = None
        self._menu: Any = None
        self._icon: Any = None
        self._icon_handle = 0
        self._icon_rgb: tuple[int, int, int] | None = None
        self._dot_images: list[Any] = []
        self._dot_theme: str | None = None
        self._desired: State = ([], "", (0, 0, 0), "")
        self._applied: tuple[Any, ...] | None = None
        self._deferred: tuple[Any, ...] | None = None
        self._stopped = False

    def run(self) -> None:
        """Crea la ventana oculta y el icono, y bloquea con el bombeo de mensajes.

        Todo el ciclo de vida de WinForms (`Form`, `NotifyIcon`, `ContextMenuStrip`) vive en
        este hilo, que se inicializa como STA para que COM y WinForms funcionen igual que en
        el hilo principal de la aplicacion.
        """
        api = self._api
        _co_initialize_apartment()
        try:
            form = self._create_form()
            notify = api.forms.NotifyIcon()
            notify.MouseClick += self._on_mouse_click
            with self._lock:
                self._form = form
                self._notify = notify
                state = self._desired
                stopped = self._stopped
            if stopped:
                return
            # El primer estado se aplica en el propio hilo de la vista, antes del bombeo.
            self._apply_native(state)
            api.forms.Application.Run(form)
        except Exception:
            _LOGGER.exception("The WinForms tray message loop failed.")
        finally:
            self._dispose_native()

    def stop(self) -> None:
        """Oculta el icono y cierra la ventana para que `run` retorne."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            form = self._form
        if form is None:
            return

        def _shutdown() -> None:
            with self._lock:
                notify = self._notify
            if notify is not None:
                notify.Visible = False
            form.Close()

        self._marshal(form, _shutdown)

    def apply(
        self,
        spec: list[TrayMenuEntry],
        title: str,
        rgb: tuple[int, int, int],
        theme: str,
    ) -> None:
        """Aplica el estado desde cualquier hilo, marshando al hilo de la vista."""
        state: State = (list(spec), title, tuple(rgb), str(theme or ""))
        signature = _signature(state)
        with self._lock:
            self._desired = state
            if self._stopped:
                return
            form = self._form
            if signature == self._applied and self._deferred is None:
                return
        if form is None:
            # La vista todavia no arranco: `run` aplica el estado al crear el icono.
            return
        self._marshal(form, lambda: self._apply_native(state))

    def _create_form(self) -> Any:
        """Ventana invisible que solo existe para hospedar el bombeo de mensajes."""
        api = self._api
        form = api.forms.Form()
        form.ShowInTaskbar = False
        form.FormBorderStyle = getattr(api.forms.FormBorderStyle, "None")
        form.Opacity = 0
        form.WindowState = api.forms.FormWindowState.Minimized
        form.Size = api.drawing.Size(0, 0)
        form.Text = ICON_NAME
        return form

    def _apply_native(self, state: State) -> None:
        """Aplica el estado en el hilo de la vista (nunca desde otro hilo)."""
        spec, title, rgb, theme = state
        signature = _signature(state)
        with self._lock:
            if signature == self._applied and self._deferred is None:
                return
            notify, menu = self._notify, self._menu
        if notify is None:
            return
        if menu is not None and menu.Visible:
            # Reemplazar el menu desplegado debajo del usuario dejaria items muertos: se
            # reintenta en el proximo refresco, igual que la vista de pystray (T-3.6).
            with self._lock:
                first_attempt = signature != self._deferred
                self._deferred = signature
            if first_attempt:
                log_applied_menu(spec, deferred=True)
            return
        palette = resolve_palette(theme)
        try:
            icon = self._icon_for(rgb)
            if icon is not None:
                notify.Icon = icon
            notify.Text = title[:NOTIFY_TEXT_LIMIT]
            new_menu = self._build_menu(spec, palette)
            notify.ContextMenuStrip = new_menu
            notify.Visible = True
        except Exception:
            _LOGGER.exception("Failed to apply the tray menu.")
            return
        with self._lock:
            previous, self._menu = self._menu, new_menu
            self._applied = signature
            self._deferred = None
        if previous is not None:
            _dispose_menu(previous)
        log_applied_menu(spec)

    def _build_menu(self, spec: Sequence[TrayMenuEntry], palette: TrayPalette) -> Any:
        """Crea el `ContextMenuStrip` completo con la paleta del tema activo."""
        api = self._api
        menu = api.forms.ContextMenuStrip()
        # `System`: el renderer del sistema pinta el fondo del dropdown con `BackColor` (el
        # renderer profesional pinta una banda negra en el margen de imagen y degradados
        # claros en la seleccion, imposibles de recolorear sin subclasificar el renderer).
        menu.RenderMode = api.forms.ToolStripRenderMode.System
        menu.BackColor = _color(palette.background, api)
        menu.ForeColor = _color(palette.text, api)
        menu.ShowCheckMargin = False
        check_image = self._check_image(palette)
        for item in _build_menu_items(
            spec,
            palette,
            self._dispatch,
            api=api,
            check_image=check_image,
        ):
            menu.Items.Add(item)
        return menu

    def _check_image(self, palette: TrayPalette) -> Any:
        """Punto de color cacheado por paleta (lo comparten todos los menus del tema)."""
        with self._lock:
            if self._dot_theme == palette.background and self._dot_images:
                return self._dot_images[-1]
        image = _dot_image(palette, self._api)
        with self._lock:
            self._dot_theme = palette.background
            self._dot_images.append(image)
        return image

    def _icon_for(self, rgb: tuple[int, int, int]) -> Any:
        """Icono cacheado por color: un refresco con el mismo tinte no asigna nada nuevo."""
        with self._lock:
            if self._icon_rgb == rgb and self._icon is not None:
                return self._icon
        icon, handle = _build_icon_image(rgb, self._api)
        with self._lock:
            previous, previous_handle = self._icon, self._icon_handle
            self._icon, self._icon_handle, self._icon_rgb = icon, handle, rgb
        if previous is not None:
            previous.Dispose()
        if previous_handle:
            self._destroy_icon(previous_handle)
        return icon

    def _on_mouse_click(self, sender: Any, event_args: Any) -> None:
        """Clic izquierdo sobre el icono: despacha la accion por defecto del modelo."""
        try:
            if event_args.Button != self._api.forms.MouseButtons.Left:
                return
        except Exception:
            _LOGGER.debug("Tray mouse event without a button could not be read.", exc_info=True)
            return
        with self._lock:
            spec = list(self._desired[0])
        for entry in spec:
            if entry.is_default:
                target = resolve_entry_action(entry)
                if target is not None:
                    self._dispatch(target[0], target[1])
                return

    def _marshal(self, form: Any, action: Callable[[], None]) -> None:
        """Ejecuta `action` en el hilo del bucle de mensajes de la vista."""
        try:
            if form.IsHandleCreated and form.InvokeRequired:
                form.Invoke(self._api.action(action))
                return
            action()
        except Exception:
            _LOGGER.exception("WinForms tray update failed.")

    def _dispose_native(self) -> None:
        """Libera icono, menu, imagenes, `HICON` y la ventana en el hilo de la vista."""
        with self._lock:
            form, notify, menu = self._form, self._notify, self._menu
            icon, handle = self._icon, self._icon_handle
            images = self._dot_images
            self._form = self._notify = self._menu = self._icon = None
            self._icon_handle = 0
            self._icon_rgb = None
            self._dot_images = []
        if notify is not None:
            try:
                notify.Visible = False
                notify.Dispose()
            except Exception:
                _LOGGER.debug("Tray icon disposal failed.", exc_info=True)
        if menu is not None:
            _dispose_menu(menu)
        for image in images:
            try:
                image.Dispose()
            except Exception:
                _LOGGER.debug("Check dot disposal failed.", exc_info=True)
        if icon is not None:
            try:
                icon.Dispose()
            except Exception:
                _LOGGER.debug("Tray icon image disposal failed.", exc_info=True)
        if handle:
            self._destroy_icon(handle)
        if form is not None:
            try:
                form.Dispose()
            except Exception:
                _LOGGER.debug("Tray form disposal failed.", exc_info=True)


def _dispose_menu(menu: Any) -> None:
    """Descarta un menu que ya no se muestra."""
    try:
        menu.Dispose()
    except Exception:
        _LOGGER.debug("Tray menu disposal failed.", exc_info=True)
