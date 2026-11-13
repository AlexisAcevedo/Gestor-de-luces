"""Capa de escritorio: ciclo de vida de la ventana nativa, la bandeja y el menu.

Este paquete aloja el ensamblado de adaptadores de escritorio (pywebview, bandeja del
sistema y capa de plataforma Windows) para que `main.py` quede como raiz de composicion.
"""

from __future__ import annotations

from gestor_luces.desktop.app import DesktopApplication

__all__ = ["DesktopApplication"]
