"""Adaptador primario de bandeja del sistema (System Tray) para Windows.

Reexporta el controlador de bandeja, el contrato de vista y las funciones puras del modelo
de menu e icono para que el punto de entrada y las pruebas interactuen con una interfaz
unica sin acoplarse a la organizacion interna de los modulos. Las vistas concretas
(`winforms_tray` y el respaldo `pystray_tray`) se importan desde su propio modulo para no
cargar .NET ni `pystray` cuando el arranque no llega a la bandeja.
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
from gestor_luces.adapters.tray.tray_view import (
    Dispatch,
    TrayView,
    resolve_entry_action,
)

__all__ = [
    "Dispatch",
    "TrayController",
    "TrayMenuEntry",
    "TrayPreset",
    "TrayView",
    "build_tray_menu_spec",
    "build_tray_title",
    "render_icon_image",
    "resolve_entry_action",
    "resolve_icon_rgb",
]
