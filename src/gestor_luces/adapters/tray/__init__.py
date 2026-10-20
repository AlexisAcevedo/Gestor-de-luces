"""Adaptador primario de bandeja del sistema (System Tray) para Windows.

Reexporta el controlador de bandeja y las funciones puras del modelo de menu e
icono para que el punto de entrada (`main.py`) y las pruebas interactuen con una
interfaz unica sin acoplarse a la organizacion interna de los modulos.
"""

from __future__ import annotations

from gestor_luces.adapters.tray.menu_model import (
    TrayMenuEntry,
    TrayPreset,
    build_tray_menu_spec,
    build_tray_title,
    resolve_icon_rgb,
)
from gestor_luces.adapters.tray.tray_icon import (
    TrayController,
    render_icon_image,
)

__all__ = [
    "TrayController",
    "TrayMenuEntry",
    "TrayPreset",
    "build_tray_menu_spec",
    "build_tray_title",
    "render_icon_image",
    "resolve_icon_rgb",
]
