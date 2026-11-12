"""Chrome de ventana Win32: atributo DWM de barra de titulo oscura y utilidades nativas.

Cada funcion acepta la DLL Win32 cruda (`dwmapi=`) como dependencia inyectable, de modo
que se puede probar sin una ventana real ni una sesion de escritorio.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_LOGGER = logging.getLogger(__name__)


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
            20,  # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.byref(value),
            ctypes.sizeof(ctypes.c_int),
        )
        return True
    except Exception:
        _LOGGER.debug("Windows dark titlebar attribute skipped.", exc_info=True)
        return False
