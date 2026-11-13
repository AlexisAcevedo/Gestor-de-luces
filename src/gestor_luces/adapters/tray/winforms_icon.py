"""Icono de bandeja nativo: `NotifyIcon`, cache de `HICON` por color y tooltip.

`NotifyIcon` es la pieza que Windows muestra junto al reloj. La vista aplica el tinte del
icono en cada refresco (el color del haz de luz cambia con el estado de la lampara), asi
que este modulo mantiene un icono por color y libera el `HICON` anterior: `GetHicon()` crea
un handle que Windows no libera solo y filtraria recursos en cada refresco.

El tooltip (`NotifyIcon.Text`) se recorta a `NOTIFY_TEXT_LIMIT` caracteres porque un texto
mas largo lanza una excepcion de .NET. Ninguna de estas piezas crea ventanas ni toca el
menu: son objetos del hilo de la vista, aplicados ya marshalizados.
"""

from __future__ import annotations

import ctypes
import io
import logging
import threading
from collections.abc import Callable
from typing import Any

from gestor_luces.adapters.platform.windows.window_chrome import NATIVE_CALL_ERRORS
from gestor_luces.adapters.tray.tray_view import render_icon_image
from gestor_luces.adapters.tray.winforms_host import _WinFormsApi, release_native

_LOGGER = logging.getLogger(__name__)

#: `NotifyIcon.Text` admite 63 caracteres; un texto mas largo lanza una excepcion.
NOTIFY_TEXT_LIMIT = 63

DestroyIcon = Callable[[int], None]


def _destroy_icon_handle(handle: int) -> None:
    """Libera un `HICON` creado con `Bitmap.GetHicon()` (Windows no lo libera solo)."""
    try:
        ctypes.windll.user32.DestroyIcon(handle)
    # `DestroyIcon` es una llamada `ctypes` pura: solo falla con `NATIVE_CALL_ERRORS`.
    except NATIVE_CALL_ERRORS:
        _LOGGER.debug("DestroyIcon failed for handle %s.", handle, exc_info=True)


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


class IconCache:
    """Iconos de la bandeja cacheados por color, con liberacion del `HICON` reemplazado."""

    def __init__(self, api: _WinFormsApi, *, destroy_icon: DestroyIcon | None = None) -> None:
        self._api = api
        self._destroy_icon = destroy_icon or _destroy_icon_handle
        self._lock = threading.Lock()
        self._icon: Any = None
        self._handle = 0
        self._rgb: tuple[int, int, int] | None = None

    @property
    def current_rgb(self) -> tuple[int, int, int] | None:
        """Color del icono vigente (`None` si todavia no se creo ninguno)."""
        with self._lock:
            return self._rgb

    def icon_for(self, rgb: tuple[int, int, int]) -> Any:
        """Icono cacheado por color: un refresco con el mismo tinte no asigna nada nuevo."""
        with self._lock:
            if self._rgb == rgb and self._icon is not None:
                return self._icon
        icon, handle = _build_icon_image(rgb, self._api)
        with self._lock:
            previous, previous_handle = self._icon, self._handle
            self._icon, self._handle, self._rgb = icon, handle, rgb
        if previous is not None:
            previous.Dispose()
        if previous_handle:
            self._destroy_icon(previous_handle)
        return icon

    def dispose(self) -> None:
        """Libera el icono vigente y su `HICON` (la cache queda vacia)."""
        with self._lock:
            icon, handle = self._icon, self._handle
            self._icon, self._handle, self._rgb = None, 0, None
        if icon is not None:
            release_native(
                icon.Dispose,
                self._api,
                what="Tray icon image disposal",
            )
        if handle:
            self._destroy_icon(handle)


def create_notify_icon(api: _WinFormsApi, *, on_click: Callable[..., None]) -> Any:
    """Crea el `NotifyIcon` y engancha el clic del icono (vista, no menu)."""
    notify = api.forms.NotifyIcon()
    notify.MouseClick += on_click
    return notify


def apply_notify_state(notify: Any, *, title: str, icon: Any = None) -> None:
    """Aplica tooltip e icono y hace visible el icono la primera vez."""
    if icon is not None:
        notify.Icon = icon
    notify.Text = title[:NOTIFY_TEXT_LIMIT]
    if not notify.Visible:
        notify.Visible = True


def dispose_notify(notify: Any, api: _WinFormsApi) -> None:
    """Oculta y descarta el `NotifyIcon` (en el hilo de la vista)."""
    if notify is None:
        return

    def _teardown() -> None:
        notify.Visible = False
        notify.Dispose()

    release_native(_teardown, api, what="Tray icon disposal")
