"""Traer la ventana nativa al frente (Win32 foreground activation).

`user32` es inyectable para poder probar la secuencia de llamadas sin una ventana real.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from gestor_luces.adapters.platform.windows.window_chrome import (
    NATIVE_CALL_ERRORS,
    _configure_fn_signature,
    _resolve_native_hwnd,
)

_LOGGER = logging.getLogger(__name__)


def _activate_window_foreground(
    window: Any,
    *,
    platform: str = sys.platform,
    user32: Any = None,
) -> bool:
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

        target_user32 = ctypes.windll.user32 if user32 is None else user32
        _configure_fn_signature(
            getattr(target_user32, "ShowWindow", None),
            [wintypes.HWND, ctypes.c_int],
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
        _configure_fn_signature(
            getattr(target_user32, "SetForegroundWindow", None),
            [wintypes.HWND],
            wintypes.BOOL,
        )
        target_user32.ShowWindow(hwnd, 9)
        target_user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
        target_user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)
        target_user32.SetForegroundWindow(hwnd)
        return True
    except NATIVE_CALL_ERRORS:
        # `ShowWindow`/`SetWindowPos`/`SetForegroundWindow` pueden faltar o rechazar el
        # handle: la ventana se queda donde esta y el llamador no ve una excepcion.
        _LOGGER.debug("Native foreground activation skipped.", exc_info=True)
        return False
