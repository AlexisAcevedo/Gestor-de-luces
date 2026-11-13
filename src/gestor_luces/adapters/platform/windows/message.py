"""Cuadro de mensaje nativo de Windows (`MessageBoxW`).

`user32` es inyectable para poder probar la llamada sin abrir una ventana real. Fuera de
Windows el texto solo se registra en el log, igual que hacia la accion "Acerca de".
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_LOGGER = logging.getLogger(__name__)

# MB_OK | MB_ICONINFORMATION
_MESSAGE_BOX_FLAGS = 0x40


def show_message_box(
    text: str,
    title: str,
    *,
    platform: str = sys.platform,
    user32: Any = None,
) -> None:
    """Muestra `text` en un cuadro de mensaje nativo; fuera de Windows solo lo registra."""
    if platform != "win32":
        _LOGGER.info("%s", text)
        return
    import ctypes

    target_user32 = ctypes.windll.user32 if user32 is None else user32
    target_user32.MessageBoxW(0, text, title, _MESSAGE_BOX_FLAGS)
