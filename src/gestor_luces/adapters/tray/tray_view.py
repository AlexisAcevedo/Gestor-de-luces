"""Contrato entre el controlador de bandeja y sus vistas nativas.

`TrayController` posee el modelo de menu, los handlers y el ejecutor de acciones; la vista
solo dibuja el icono y el menu y traduce un clic en la accion que corresponde. Separar
ambas piezas permite que el menu clasico de `pystray` quede como respaldo de una vista
nativa de WinForms con colores explicitos, sin tocar el despacho de acciones ni la
politica de hilos del controlador.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from PIL import Image

from gestor_luces.adapters.tray.bulb_icon import render_bulb_image
from gestor_luces.adapters.tray.menu_model import (
    ACTION_HIDE_WINDOW,
    ACTION_SHOW_WINDOW,
    TrayMenuEntry,
)

_LOGGER = logging.getLogger(__name__)

ICON_NAME = "gestor_luces"
ICON_SIZE = 64

#: Accion sintetica que despacha un item por defecto (mostrar/ocultar ventana).
WINDOW_TOGGLE_ACTION = "toggle_window"

_WINDOW_TOGGLE_ACTIONS = frozenset({ACTION_SHOW_WINDOW, ACTION_HIDE_WINDOW})

#: Firma con la que la vista entrega una accion al controlador.
Dispatch = Callable[[str, Any], None]


class TrayView(Protocol):
    """Vista nativa de la bandeja del sistema.

    Contrato minimo que comparten `winforms_tray` (vista principal) y `pystray_tray`
    (respaldo): `run` bloquea el hilo llamador, `apply` se invoca desde el hilo de
    refresco y `stop` es seguro desde cualquier hilo.
    """

    def run(self) -> None:
        """Muestra el icono y bloquea el hilo llamador hasta que se invoque `stop`."""

    def stop(self) -> None:
        """Retira el icono y hace que `run` retorne; segura de invocar varias veces."""

    def apply(
        self,
        spec: list[TrayMenuEntry],
        title: str,
        rgb: tuple[int, int, int],
        theme: str,
    ) -> None:
        """Aplica modelo de menu, tooltip, tinte del icono y tema activo.

        Es segura desde cualquier hilo: cada vista marshaliza el trabajo a su propio hilo
        de bombeo cuando hace falta y descarta un estado identico al ultimo aplicado.
        """


def render_icon_image(rgb: tuple[int, int, int], size: int = ICON_SIZE) -> Image.Image:
    """Dibuja la bombilla de la aplicacion teñida con el color del haz."""
    return render_bulb_image(rgb, size)


def resolve_entry_action(entry: TrayMenuEntry) -> tuple[str, Any] | None:
    """Traduce una hoja del modelo a la accion que la vista debe despachar.

    Las entradas por defecto (mostrar/ocultar ventana) despachan la accion sintetica
    `toggle_window`, igual que el handler historico de `TrayController`: un clic sobre el
    icono oculto siempre abre la ventana aunque el modelo cacheado este desfasado.
    """
    if entry.is_separator or not entry.action_id:
        return None
    if entry.is_default and entry.action_id in _WINDOW_TOGGLE_ACTIONS:
        return (WINDOW_TOGGLE_ACTION, None)
    return (entry.action_id, entry.payload)


def log_applied_menu(spec: Sequence[TrayMenuEntry], *, deferred: bool = False) -> None:
    """Registra una linea por estado de menu aplicado (rastro para el checklist manual)."""
    _LOGGER.info(
        "Tray menu %s: %s",
        "rebuild deferred (menu open)" if deferred else "rebuilt",
        [(entry.label, entry.action_id) for entry in spec],
    )
