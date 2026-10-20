"""Modelo puro del menu de la bandeja del sistema.

Este modulo no importa `pystray` a proposito: describe el menu con dataclasses
inmutables para poder probar su contenido (etiquetas, radios, favoritos) sin crear
iconos reales ni depender de un escritorio Win32 durante las pruebas automatizadas.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

ACTION_SHOW_WINDOW = "show_window"
ACTION_HIDE_WINDOW = "hide_window"
ACTION_TURN_ON = "turn_on"
ACTION_TURN_OFF = "turn_off"
ACTION_SET_BRIGHTNESS = "set_brightness"
ACTION_APPLY_PRESET = "apply_preset"
ACTION_CANCEL_SLEEP_TIMER = "cancel_sleep_timer"
ACTION_QUIT = "quit"

BRIGHTNESS_LEVELS: tuple[int, ...] = (10, 25, 50, 75, 100)
FALLBACK_PRESET_LIMIT = 8
OFF_ICON_RGB: tuple[int, int, int] = (0x5A, 0x62, 0x70)
SCENE_ICON_RGB: tuple[int, int, int] = (0xFF, 0x92, 0x54)


@dataclass(frozen=True)
class TrayPreset:
    """Referencia minima a un preset personalizado para listarlo en la bandeja."""

    id: str
    name: str
    is_favorite: bool = False


@dataclass(frozen=True)
class TrayMenuEntry:
    """Descripcion de una entrada del menu independiente del toolkit grafico.

    `checked` vale None para entradas no marcables, de modo que el traductor a
    pystray pueda distinguir una casilla desmarcada de una accion simple.
    """

    label: str = ""
    action_id: str = ""
    payload: Any = None
    checked: bool | None = None
    enabled: bool = True
    is_separator: bool = False
    children: tuple[TrayMenuEntry, ...] = ()
    radio: bool = False
    is_default: bool = False


SEPARATOR = TrayMenuEntry(is_separator=True)


def closest_brightness_level(brightness: int) -> int:
    """Elige el nivel predefinido mas cercano; ante empate prefiere el menor."""
    return min(BRIGHTNESS_LEVELS, key=lambda level: (abs(level - brightness), level))


def select_tray_presets(presets: Sequence[TrayPreset]) -> list[TrayPreset]:
    """Prioriza los favoritos y, si no hay ninguno, ofrece los primeros presets guardados.

    El respaldo evita que el submenu quede vacio para usuarios que aun no marcaron
    favoritos, sin inundar el menu cuando existen decenas de presets.
    """
    favorites = [preset for preset in presets if preset.is_favorite]
    if favorites:
        return favorites
    return list(presets[:FALLBACK_PRESET_LIMIT])


def build_tray_menu_spec(
    *,
    is_on: bool,
    brightness: int,
    presets: Sequence[TrayPreset],
    window_visible: bool,
    sleep_timer_active: bool,
) -> list[TrayMenuEntry]:
    """Construye la estructura completa del menu a partir del estado actual."""
    entries: list[TrayMenuEntry] = [
        TrayMenuEntry(
            label="Hide window" if window_visible else "Show window",
            action_id=ACTION_HIDE_WINDOW if window_visible else ACTION_SHOW_WINDOW,
            is_default=True,
        ),
        SEPARATOR,
        TrayMenuEntry(
            label="Turn off" if is_on else "Turn on",
            action_id=ACTION_TURN_OFF if is_on else ACTION_TURN_ON,
        ),
        TrayMenuEntry(label="Brightness", children=_build_brightness_entries(brightness)),
        TrayMenuEntry(label="Favorite presets", children=_build_preset_entries(presets)),
    ]
    if sleep_timer_active:
        entries.append(
            TrayMenuEntry(label="Cancel sleep timer", action_id=ACTION_CANCEL_SLEEP_TIMER)
        )
    entries.extend([SEPARATOR, TrayMenuEntry(label="Quit", action_id=ACTION_QUIT)])
    return entries


def _build_brightness_entries(brightness: int) -> tuple[TrayMenuEntry, ...]:
    """Genera los niveles de brillo como grupo radio con el nivel vigente marcado."""
    selected = closest_brightness_level(brightness)
    return tuple(
        TrayMenuEntry(
            label=f"{level}%",
            action_id=ACTION_SET_BRIGHTNESS,
            payload=level,
            checked=level == selected,
            radio=True,
        )
        for level in BRIGHTNESS_LEVELS
    )


def _build_preset_entries(presets: Sequence[TrayPreset]) -> tuple[TrayMenuEntry, ...]:
    """Genera las entradas de presets o un marcador deshabilitado si no existen."""
    selected = select_tray_presets(presets)
    if not selected:
        return (TrayMenuEntry(label="No saved presets", enabled=False),)
    return tuple(
        TrayMenuEntry(label=preset.name, action_id=ACTION_APPLY_PRESET, payload=preset.id)
        for preset in selected
    )


def build_tray_title(is_on: bool, brightness: int) -> str:
    """Texto del tooltip del icono, visible al pasar el cursor sobre la bandeja."""
    if is_on:
        return f"WiZ Lighting - On {brightness}%"
    return "WiZ Lighting - Off"


def kelvin_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """Aproxima una temperatura de blanco a RGB con la misma rampa que usa la UI web.

    Replicar la interpolacion de `kelvinToCssColor` en app.js mantiene coherente el
    tinte del icono con el color del haz que el usuario ve en la ventana.
    """
    k = max(2200, min(6500, int(kelvin)))
    if k <= 4200:
        t = (k - 2200) / (4200 - 2200)
        start, end = (255, 180, 107), (255, 241, 224)
    else:
        t = (k - 4200) / (6500 - 4200)
        start, end = (255, 241, 224), (214, 232, 255)
    r, g, b = (round(a + (z - a) * t) for a, z in zip(start, end))
    return (r, g, b)


def resolve_icon_rgb(
    *,
    is_on: bool,
    mode: str | None,
    color: Sequence[int] | None,
    temperature: int | None,
) -> tuple[int, int, int]:
    """Determina el tinte del icono segun el modo luminico del foco de referencia."""
    if not is_on:
        return OFF_ICON_RGB
    if mode == "rgb" and color is not None and len(color) == 3:
        r, g, b = (max(0, min(255, int(channel))) for channel in color)
        return (r, g, b)
    if mode == "scene":
        return SCENE_ICON_RGB
    return kelvin_to_rgb(temperature if temperature is not None else 4200)
