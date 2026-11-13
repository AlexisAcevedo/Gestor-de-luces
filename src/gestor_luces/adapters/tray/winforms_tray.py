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
colores por control (`BackColor`/`ForeColor`) y el dibujo de cada fila se hace a mano en
el evento `ToolStripItem.Paint`, que .NET emite despues del render del sistema.

Acabado moderno (T-3.9): el render del sistema dibuja filas de ~20 px, un borde de 1 px
en el color del tema de Windows y un resaltado plano, que el usuario reconocio como un
menu de Windows 98. La vista ahora:
- pide esquinas redondeadas a DWM (`DWMWA_WINDOW_CORNER_PREFERENCE`) y aplica ademas una
  region redondeada recortada 1 px, que es el unico mecanismo disponible sin subclasificar
  el renderer para quitar el borde del sistema (una region propia impide que DWM redondee
  la ventana, asi que la region es la fuente efectiva de las esquinas);
- sube el padding vertical de cada fila para llegar a ~28 px;
- pinta fondo, hover, texto, marca de nivel activo y flecha de submenu con la paleta, y
  los separadores con su propio color (`TrayPalette.separator`);
- separa la firma del menu `(tuple(spec), theme)` de la firma del estado
  `(menu signature, title, rgb)`, de modo que un cambio de tooltip o de tinte del icono
  nunca reconstruye el `ContextMenuStrip`.

`pythonnet` se importa dentro de `_load_winforms()` (nunca al importar el modulo) para que
el paquete se pueda usar en Linux/CI sin CLR y para que la vista degradada a `pystray`
sea siempre posible.
"""

from __future__ import annotations

import ctypes
import io
import logging
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from gestor_luces.adapters.platform.windows.window_chrome import _apply_corner_preference
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

#: Padding vertical de cada fila: la fuente de 9 pt mide ~20 px, asi que 4 por lado da
#: filas de ~28 px (objetivo 26-28) sin depender del tamano de fuente del sistema.
MENU_ITEM_PADDING_VERTICAL = 4
#: Margen izquierdo del texto (8-10 px modernos) y del punto del nivel activo, en px.
MENU_ITEM_TEXT_INSET = 10
MENU_ITEM_CHECK_INSET = 6
MENU_ITEM_CHECK_DOT = 6
#: Distancia de la flecha de submenu al borde derecho, y grosor de su trazo.
MENU_ITEM_ARROW_INSET = 11
MENU_ITEM_ARROW_WIDTH = 1.3
#: Margen horizontal de la linea separadora.
MENU_SEPARATOR_INSET = 10
#: Radio de esquina (px logicos) y recorte que elimina el borde de 1 px del renderer.
MENU_CORNER_RADIUS = 8
MENU_EDGE_INSET = 1

DestroyIcon = Callable[[int], None]

#: Estado deseado: modelo de menu, tooltip, color del icono y tema activo.
State = tuple[list[TrayMenuEntry], str, tuple[int, int, int], str]
#: Firma que obliga a reconstruir el `ContextMenuStrip`.
MenuSignature = tuple[tuple[TrayMenuEntry, ...], str]
#: Firma del estado completo, incluidos tooltip y tinte del icono.
StateSignature = tuple[MenuSignature, str, tuple[int, int, int]]


@dataclass(frozen=True)
class TrayPalette:
    """Colores explicitos del menu de bandeja, independientes del tema de Windows."""

    background: str
    text: str
    disabled_text: str
    selection: str
    separator: str


LIGHT_PALETTE = TrayPalette(
    background="#F7F5F2",
    text="#1C1C1F",
    disabled_text="#8A8A8E",
    selection="#E4DED6",
    separator="#D9D1C6",
)
DARK_PALETTE = TrayPalette(
    background="#1B1B1F",
    text="#E6E6EA",
    disabled_text="#7A7A82",
    selection="#2A2A31",
    separator="#3A3A42",
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


@dataclass(frozen=True)
class ItemPaintStyle:
    """Colores con los que se dibuja una fila del menu.

    `mark` es el punto del nivel de brillo activo en una fila marcable y el color de la
    linea en un separador; `background` es el hover cuando la fila esta seleccionada.
    """

    background: str
    text: str
    mark: str


def item_paint_style(
    palette: TrayPalette,
    *,
    hovered: bool,
    enabled: bool = True,
) -> ItemPaintStyle:
    """Colores de una fila: hover con `selection`, texto atenuado si esta deshabilitada."""
    return ItemPaintStyle(
        background=palette.selection if hovered else palette.background,
        text=palette.text if enabled else palette.disabled_text,
        mark=palette.text,
    )


def separator_paint_style(palette: TrayPalette) -> ItemPaintStyle:
    """Colores de un separador: fondo del menu (sin banda) y linea propia de la paleta."""
    return ItemPaintStyle(
        background=palette.background,
        text=palette.separator,
        mark=palette.separator,
    )


def menu_signature(spec: Sequence[TrayMenuEntry], theme: str) -> MenuSignature:
    """Firma del menu: todo lo que obliga a reconstruir el `ContextMenuStrip`."""
    return (tuple(spec), str(theme or ""))


def state_signature(
    spec: Sequence[TrayMenuEntry],
    title: str,
    rgb: tuple[int, int, int],
    theme: str,
) -> StateSignature:
    """Firma del estado completo; un cambio de tooltip o de tinte solo toca el icono."""
    return (menu_signature(spec, theme), str(title), tuple(rgb))


def menu_region_geometry(
    width: int,
    height: int,
    *,
    radius: int = MENU_CORNER_RADIUS,
    inset: int = MENU_EDGE_INSET,
    scale: float = 1.0,
) -> tuple[int, int, int, int, int] | None:
    """Rectangulo redondeado `(left, top, right, bottom, radius)` recortado por `inset`.

    El recorte de 1 px deja fuera de la ventana el borde que dibuja el renderer del
    sistema; `scale` convierte el radio logico al DPI de la ventana. Devuelve `None` si el
    menu es demasiado chico para redondearlo, para que la vista no cree una region invalida.
    """
    if width <= 2 * inset + 2 or height <= 2 * inset + 2:
        return None
    left, top = int(inset), int(inset)
    right, bottom = int(width) - int(inset), int(height) - int(inset)
    candidate = max(1, int(round(int(radius) * max(float(scale), 0.1))))
    limit = (min(right - left, bottom - top) - 2) // 2
    if limit < 1:
        return None
    return (left, top, right, bottom, max(1, min(candidate, limit)))


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


def _item_draw_width(sender: Any) -> int:
    """Ancho visible de la fila: el item puede sobresalir del menu por su propio padding."""
    width = int(getattr(sender, "Width", 0) or 0)
    try:
        owner = sender.Owner
        owner_width = int(owner.Width) - int(sender.Bounds.X)
    except Exception:
        owner_width = width
    if owner_width > 0:
        width = min(width, owner_width)
    return max(1, width)


def paint_menu_item(
    graphics: Any,
    *,
    palette: TrayPalette,
    api: _WinFormsApi,
    text: str,
    font: Any,
    width: int,
    height: int,
    hovered: bool,
    enabled: bool = True,
    checked: bool = False,
    has_children: bool = False,
) -> ItemPaintStyle:
    """Dibuja una fila completa (fondo, hover, texto, marca y flecha) con la paleta.

    Reemplaza el dibujo del renderer del sistema, que pinta un resaltado plano y un glifo
    de check con color fijo (invisible sobre el tema oscuro). Devuelve el estilo usado para
    que las pruebas verifiquen colores sin comparar pixeles de una ventana real.
    """
    drawing = api.drawing
    style = item_paint_style(palette, hovered=hovered, enabled=enabled)
    background = drawing.SolidBrush(_color(style.background, api))
    try:
        graphics.FillRectangle(background, drawing.Rectangle(0, 0, width, height))
    finally:
        background.Dispose()
    text_left = MENU_ITEM_TEXT_INSET
    foreground = drawing.SolidBrush(_color(style.text, api))
    try:
        if checked:
            dot = drawing.SolidBrush(_color(style.mark, api))
            try:
                graphics.FillEllipse(
                    dot,
                    MENU_ITEM_CHECK_INSET,
                    (height - MENU_ITEM_CHECK_DOT) // 2,
                    MENU_ITEM_CHECK_DOT,
                    MENU_ITEM_CHECK_DOT,
                )
            finally:
                dot.Dispose()
            text_left = MENU_ITEM_TEXT_INSET + MENU_ITEM_CHECK_DOT + 2
        right_inset = MENU_ITEM_ARROW_INSET + 7 if has_children else MENU_ITEM_TEXT_INSET
        line_format = drawing.StringFormat()
        try:
            line_format.LineAlignment = drawing.StringAlignment.Center
            line_format.FormatFlags = drawing.StringFormatFlags.NoWrap
            graphics.DrawString(
                text,
                font,
                foreground,
                drawing.RectangleF(
                    text_left,
                    0,
                    max(1, width - text_left - right_inset),
                    height,
                ),
                line_format,
            )
        finally:
            line_format.Dispose()
    finally:
        foreground.Dispose()
    if has_children:
        arrow = drawing.Pen(_color(style.text, api), MENU_ITEM_ARROW_WIDTH)
        try:
            center_x = width - MENU_ITEM_ARROW_INSET
            center_y = height // 2
            graphics.DrawLine(arrow, center_x - 2, center_y - 3, center_x + 1, center_y)
            graphics.DrawLine(arrow, center_x + 1, center_y, center_x - 2, center_y + 3)
        finally:
            arrow.Dispose()
    return style


def paint_menu_separator(
    graphics: Any,
    *,
    palette: TrayPalette,
    api: _WinFormsApi,
    width: int,
    height: int,
) -> ItemPaintStyle:
    """Dibuja un separador centrado con el color propio de la paleta."""
    drawing = api.drawing
    style = separator_paint_style(palette)
    background = drawing.SolidBrush(_color(style.background, api))
    try:
        graphics.FillRectangle(background, drawing.Rectangle(0, 0, width, height))
    finally:
        background.Dispose()
    line = drawing.Pen(_color(style.mark, api), 1)
    try:
        middle = height // 2
        graphics.DrawLine(
            line,
            MENU_SEPARATOR_INSET,
            middle,
            max(MENU_SEPARATOR_INSET + 1, width - MENU_SEPARATOR_INSET),
            middle,
        )
    finally:
        line.Dispose()
    return style


def _item_paint_handler(
    palette: TrayPalette,
    api: _WinFormsApi,
    *,
    has_children: bool,
) -> Callable[..., None]:
    """Handler de `ToolStripItem.Paint` de una fila del menu."""

    def _on_paint(sender: Any, event_args: Any) -> None:
        try:
            paint_menu_item(
                event_args.Graphics,
                palette=palette,
                api=api,
                text=str(sender.Text),
                font=sender.Font,
                width=_item_draw_width(sender),
                height=int(sender.Height),
                hovered=bool(sender.Selected or sender.Pressed),
                enabled=bool(sender.Enabled),
                checked=bool(sender.Checked),
                has_children=has_children,
            )
        except Exception:
            _LOGGER.debug("Tray menu item paint failed.", exc_info=True)

    return _on_paint


def _separator_paint_handler(palette: TrayPalette, api: _WinFormsApi) -> Callable[..., None]:
    """Handler de `ToolStripItem.Paint` de un separador."""

    def _on_paint(sender: Any, event_args: Any) -> None:
        try:
            paint_menu_separator(
                event_args.Graphics,
                palette=palette,
                api=api,
                width=_item_draw_width(sender),
                height=int(sender.Height),
            )
        except Exception:
            _LOGGER.debug("Tray menu separator paint failed.", exc_info=True)

    return _on_paint


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
) -> list[Any]:
    """Traduce el modelo puro a items reales de WinForms con la paleta aplicada.

    Es pura respecto del icono: no crea la ventana ni toca el `NotifyIcon`, solo objetos
    `ToolStripMenuItem`/`ToolStripSeparator`, de modo que las pruebas pueden verificar el
    arbol y los colores sin escritorio.
    """
    resolved = api or _load_winforms()
    if resolved is None:
        raise RuntimeError("WinForms is not available in this environment")
    return [
        _build_menu_item(
            entry,
            palette,
            dispatch,
            resolved,
            background=palette.background,
        )
        for entry in spec
    ]


def _build_menu_item(
    entry: TrayMenuEntry,
    palette: TrayPalette,
    dispatch: Dispatch,
    api: _WinFormsApi,
    *,
    background: str,
) -> Any:
    """Construye un item (hoja, padre de submenu o separador) con sus colores."""
    if entry.is_separator:
        separator = api.forms.ToolStripSeparator()
        separator.Paint += _separator_paint_handler(palette, api)
        return separator
    item = api.forms.ToolStripMenuItem(entry.label)
    item.BackColor = _color(background, api)
    item.ForeColor = _color(palette.text if entry.enabled else palette.disabled_text, api)
    item.Enabled = entry.enabled
    item.CheckOnClick = False
    # Filas altas: el alto de fuente (~20 px) mas este padding da los ~28 px modernos.
    item.Padding = api.forms.Padding(
        0,
        MENU_ITEM_PADDING_VERTICAL,
        0,
        MENU_ITEM_PADDING_VERTICAL,
    )
    if entry.checked is not None:
        item.Checked = bool(entry.checked)
    item.Paint += _item_paint_handler(palette, api, has_children=bool(entry.children))
    if entry.children:
        # Submenu real: WinForms lo despliega al pasar el cursor. No hay handler de clic en
        # el padre (un clic no debe abrir ni cerrar nada a mano).
        dropdown = item.DropDown
        dropdown.BackColor = _color(palette.background, api)
        dropdown.ForeColor = _color(palette.text, api)
        dropdown.ShowCheckMargin = False
        dropdown.ShowImageMargin = False
        for child in entry.children:
            dropdown.Items.Add(
                _build_menu_item(
                    child,
                    palette,
                    dispatch,
                    api,
                    background=palette.background,
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


def _dpi_scale(control: Any) -> float:
    """Factor de escala del DPI de la ventana (1.0 si el runtime no lo expone)."""
    try:
        return float(control.DeviceDpi) / 96.0
    except Exception:
        return 1.0


def create_winforms_view(
    dispatch: Dispatch,
    *,
    destroy_icon: DestroyIcon | None = None,
    api: _WinFormsApi | None = None,
    dwmapi: Any = None,
    platform: str | None = None,
) -> TrayView | None:
    """Crea la vista WinForms, o `None` si pythonnet/WinForms no estan disponibles.

    Nunca lanza: la bandeja debe seguir existiendo aunque el CLR no cargue, y con ella el
    respaldo de `pystray`.
    """
    resolved = api or _load_winforms()
    if resolved is None:
        return None
    try:
        return WinFormsTrayView(
            dispatch,
            api=resolved,
            destroy_icon=destroy_icon,
            dwmapi=dwmapi,
            platform=platform,
        )
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
        dwmapi: Any = None,
        platform: str | None = None,
    ) -> None:
        self._dispatch = dispatch
        self._api = api
        self._destroy_icon = destroy_icon or _destroy_icon_handle
        self._dwmapi = dwmapi
        self._platform = platform if platform is not None else sys.platform
        self._lock = threading.Lock()
        self._form: Any = None
        self._notify: Any = None
        self._menu: Any = None
        self._icon: Any = None
        self._icon_handle = 0
        self._icon_rgb: tuple[int, int, int] | None = None
        self._desired: State = ([], "", (0, 0, 0), "")
        self._applied: StateSignature | None = None
        self._applied_menu: MenuSignature | None = None
        self._deferred_menu: MenuSignature | None = None
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
        signature = state_signature(state[0], state[1], state[2], state[3])
        with self._lock:
            self._desired = state
            if self._stopped:
                return
            form = self._form
            if signature == self._applied and self._deferred_menu is None:
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
        """Aplica el estado en el hilo de la vista (nunca desde otro hilo).

        Tooltip y tinte del icono se aplican siempre y sin diferir: un menu desplegado no
        necesita reemplazo para eso. Solo la reconstruccion del `ContextMenuStrip` se
        difiere mientras el menu esta visible, porque reemplazarlo debajo del usuario
        dejaria items muertos (T-3.6).
        """
        spec, title, rgb, theme = state
        signature = state_signature(spec, title, rgb, theme)
        menu_key = menu_signature(spec, theme)
        with self._lock:
            if signature == self._applied and self._deferred_menu is None:
                return
            notify, menu = self._notify, self._menu
            rebuild = menu_key != self._applied_menu
            displayed = bool(getattr(menu, "Visible", False)) if menu is not None else False
            icon_changed = self._icon_rgb != tuple(rgb)
        if notify is None:
            return
        try:
            if icon_changed:
                icon = self._icon_for(rgb)
                if icon is not None:
                    notify.Icon = icon
            notify.Text = title[:NOTIFY_TEXT_LIMIT]
            if not notify.Visible:
                notify.Visible = True
        except Exception:
            _LOGGER.exception("Failed to update the tray icon.")
            return
        if rebuild and displayed:
            # Solo la reconstruccion se difiere: el icono y el tooltip ya quedaron al dia.
            with self._lock:
                first_attempt = menu_key != self._deferred_menu
                self._deferred_menu = menu_key
            if first_attempt:
                log_applied_menu(spec, deferred=True)
            return
        try:
            new_menu = self._build_menu(spec, resolve_palette(theme)) if rebuild else menu
            if rebuild:
                notify.ContextMenuStrip = new_menu
        except Exception:
            _LOGGER.exception("Failed to apply the tray menu.")
            return
        with self._lock:
            previous = self._menu
            if rebuild:
                self._menu = new_menu
                self._applied_menu = menu_key
            self._applied = signature
            self._deferred_menu = None
        if rebuild:
            if previous is not None:
                _dispose_menu(previous)
            log_applied_menu(spec)

    def _build_menu(self, spec: Sequence[TrayMenuEntry], palette: TrayPalette) -> Any:
        """Crea el `ContextMenuStrip` completo con la paleta del tema activo."""
        api = self._api
        menu = api.forms.ContextMenuStrip()
        # `System`: el renderer del sistema pinta el fondo del dropdown con `BackColor` (el
        # renderer profesional pinta una banda en el margen de imagen y degradados claros en
        # la seleccion, imposibles de recolorear sin subclasificar el renderer). Las filas,
        # el hover y los separadores los dibuja esta vista en `ToolStripItem.Paint`.
        menu.RenderMode = api.forms.ToolStripRenderMode.System
        menu.BackColor = _color(palette.background, api)
        menu.ForeColor = _color(palette.text, api)
        menu.ShowCheckMargin = False
        menu.ShowImageMargin = False
        for item in _build_menu_items(spec, palette, self._dispatch, api=api):
            menu.Items.Add(item)
        self._attach_menu_chrome(menu)
        return menu

    def _attach_menu_chrome(self, control: Any) -> None:
        """Engancha el acabado de ventana a cada menu, incluidos los submenus."""
        try:
            control.Opened += self._on_menu_opened
        except Exception:
            _LOGGER.debug("Tray menu Opened hook failed.", exc_info=True)
        for item in list(getattr(control, "Items", [])):
            try:
                has_children = int(getattr(item, "DropDownItems", None).Count) > 0
            except Exception:
                has_children = False
            if not has_children:
                continue
            try:
                dropdown = item.DropDown
            except Exception:
                _LOGGER.debug("Tray submenu unavailable for its chrome.", exc_info=True)
                continue
            self._attach_menu_chrome(dropdown)

    def _on_menu_opened(self, sender: Any, event_args: Any) -> None:
        """Aplica el acabado cuando la ventana del menu ya tiene handle."""
        try:
            self._apply_menu_chrome(sender)
        except Exception:
            _LOGGER.debug("Tray menu chrome failed.", exc_info=True)

    def _apply_menu_chrome(self, control: Any) -> None:
        """Esquinas modernas y sin borde del sistema; cada paso degrada por separado.

        Se pide primero la preferencia de DWM. Como una region propia impide que DWM
        redondee la ventana, la region recortada 1 px es la que garantiza esquinas
        redondeadas (y elimina el borde de 1 px del renderer) en cualquier Windows; si la
        region no se puede crear, el menu sigue funcionando con el borde del sistema.
        """
        _apply_corner_preference(control, platform=self._platform, dwmapi=self._dwmapi)
        self._apply_menu_region(control)

    def _apply_menu_region(self, control: Any) -> bool:
        """Recorta la ventana del menu con un rectangulo redondeado 1 px mas chico."""
        api = self._api
        size = control.Size
        geometry = menu_region_geometry(
            int(size.Width),
            int(size.Height),
            scale=_dpi_scale(control),
        )
        if geometry is None:
            return False
        try:
            from System.Drawing.Drawing2D import GraphicsPath
        except Exception:
            _LOGGER.debug("Rounded tray menu geometry unavailable.", exc_info=True)
            return False
        left, top, right, bottom, radius = geometry
        path = GraphicsPath()
        try:
            diameter = radius * 2
            path.AddArc(left, top, diameter, diameter, 180, 90)
            path.AddArc(right - diameter, top, diameter, diameter, 270, 90)
            path.AddArc(right - diameter, bottom - diameter, diameter, diameter, 0, 90)
            path.AddArc(left, bottom - diameter, diameter, diameter, 90, 90)
            path.CloseFigure()
            control.Region = api.drawing.Region(path)
        except Exception:
            _LOGGER.debug("Rounded tray menu region failed.", exc_info=True)
            return False
        finally:
            path.Dispose()
        return True

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
        """Libera icono, menu, `HICON` y la ventana en el hilo de la vista."""
        with self._lock:
            form, notify, menu = self._form, self._notify, self._menu
            icon, handle = self._icon, self._icon_handle
            self._form = self._notify = self._menu = self._icon = None
            self._icon_handle = 0
            self._icon_rgb = None
            self._applied_menu = None
        if notify is not None:
            try:
                notify.Visible = False
                notify.Dispose()
            except Exception:
                _LOGGER.debug("Tray icon disposal failed.", exc_info=True)
        if menu is not None:
            _dispose_menu(menu)
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
