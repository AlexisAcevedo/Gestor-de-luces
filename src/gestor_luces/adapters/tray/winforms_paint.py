"""Paleta y dibujo del menu de bandeja (`ContextMenuStrip`) con colores explicitos.

El renderer del sistema dibuja filas de ~20 px, un borde de 1 px en el color del tema de
Windows y un resaltado plano, que el usuario reconocio como un menu de Windows 98. Ademas
el glifo de check nativo es oscuro y desaparece sobre la paleta oscura. Por eso la vista
dibuja cada fila a mano en `ToolStripItem.Paint` (que .NET emite despues del render del
sistema) y aplica una `Region` redondeada recortada 1 px, el unico mecanismo disponible sin
subclasificar el renderer: pythonnet 3.2.1 no emite tipos derivados, asi que una
`ProfessionalColorTable` propia sale como el tipo base y nunca recibe despacho virtual.

Recibe los modulos de .NET ya resueltos por `winforms_host` y devuelve el estilo usado en
cada operacion, para que las pruebas verifiquen colores sin comparar pixeles reales.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from gestor_luces.adapters.tray.winforms_host import _WinFormsApi, clr_errors

_LOGGER = logging.getLogger(__name__)

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


def _color(value: str, api: _WinFormsApi) -> Any:
    """Convierte un color de la paleta en un `System.Drawing.Color`."""
    return api.drawing.Color.FromArgb(*parse_hex_color(value))


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


def apply_menu_region(control: Any, api: _WinFormsApi) -> bool:
    """Recorta la ventana del menu con un rectangulo redondeado 1 px mas chico.

    Este es el unico guardia de la `Region` redondeada: el import de
    `System.Drawing.Drawing2D`, la construccion del `GraphicsPath` y la asignacion de la
    `Region` son la misma pieza cosmetica (T-3.9). Si falla, el menu conserva el borde del
    sistema y no lanza nunca hacia el bucle nativo.
    """
    size = control.Size
    geometry = menu_region_geometry(
        int(size.Width),
        int(size.Height),
        scale=_dpi_scale(control),
    )
    if geometry is None:
        return False
    left, top, right, bottom, radius = geometry
    path = None
    try:
        from System.Drawing.Drawing2D import GraphicsPath

        path = GraphicsPath()
        diameter = radius * 2
        path.AddArc(left, top, diameter, diameter, 180, 90)
        path.AddArc(right - diameter, top, diameter, diameter, 270, 90)
        path.AddArc(right - diameter, bottom - diameter, diameter, diameter, 0, 90)
        path.AddArc(left, bottom - diameter, diameter, diameter, 90, 90)
        path.CloseFigure()
        control.Region = api.drawing.Region(path)
    # `ImportError` cubre un runtime sin `System.Drawing.Drawing2D`; el resto es .NET.
    except (*clr_errors(api), ImportError):
        _LOGGER.debug("Rounded tray menu region skipped.", exc_info=True)
        return False
    finally:
        if path is not None:
            path.Dispose()
    return True


def _dpi_scale(control: Any) -> float:
    """Factor de escala del DPI de la ventana (1.0 si el runtime no lo expone)."""
    try:
        return float(control.DeviceDpi) / 96.0
    # `DeviceDpi` existe desde .NET Framework 4.7; un runtime o un doble sin la propiedad
    # deja la region en el radio logico (1.0).
    except (AttributeError, TypeError, ValueError):
        return 1.0
