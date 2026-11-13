"""Sondeo del modo menu del escritorio Win32.

`pystray._win32._update_menu` destruye el HMENU y lo recrea en cada `update_menu()`;
si eso ocurre mientras el popup modal esta mostrandose, los IDs de item y los
`hSubMenu` ya creados quedan invalidados y todos los clics cancelan. Este modulo
responde, desde cualquier hilo y sin tocar el icono, si el hilo en primer plano tiene
un menu desplegado, para que la bandeja difiera la reconstruccion nativa.

La DLL `user32` es inyectable para poder probar el sondeo sin escritorio real.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Banderas documentadas de GUITHREADINFO.flags (winuser.h).
GUI_INMENUMODE = 0x00000004
GUI_SYSTEMMENUMODE = 0x00000008
GUI_POPUPMENUMODE = 0x00000010

_MENU_MODE_FLAGS = GUI_INMENUMODE | GUI_SYSTEMMENUMODE | GUI_POPUPMENUMODE


class _GuiThreadInfo(ctypes.Structure):
    """Estructura GUITHREADINFO (winuser.h); solo se lee `flags`."""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def _is_menu_open(*, platform: str = sys.platform, user32: Any = None) -> bool:
    """Return True when the foreground GUI thread has a menu displayed.

    `GetGUIThreadInfo(0, ...)` consulta el hilo de la ventana en primer plano, que es el
    del icono despues del `SetForegroundWindow` de pystray. Ante cualquier fallo asume
    que no hay menu abierto: diferir un refresco no debe romper el loop de la bandeja.
    """
    if platform != "win32":
        return False
    try:
        target = ctypes.windll.user32 if user32 is None else user32
        info = _GuiThreadInfo()
        info.cbSize = ctypes.sizeof(_GuiThreadInfo)
        if not target.GetGUIThreadInfo(0, ctypes.pointer(info)):
            return False
        return bool(int(info.flags) & _MENU_MODE_FLAGS)
    except Exception:
        _LOGGER.debug("Menu-mode probe failed; assuming no menu is open.", exc_info=True)
        return False
