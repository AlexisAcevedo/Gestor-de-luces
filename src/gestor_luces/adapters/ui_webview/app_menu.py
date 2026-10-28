"""Pure model of the native window menu bar (File / Help), independent of pywebview.

Labels are localized (en / es). The model is rebuilt on every language, visibility or
autostart change; `main.py` translates it into pywebview menu objects at startup and
pushes later updates onto the live WinForms menu strip.
"""

from __future__ import annotations

from dataclasses import dataclass

ACTION_TOGGLE_WINDOW = "toggle_window"
ACTION_TOGGLE_AUTOSTART = "toggle_autostart"
ACTION_EXIT = "exit"
ACTION_SHOW_SHORTCUTS = "show_shortcuts"
ACTION_SHOW_ABOUT = "show_about"

APP_DISPLAY_NAME = "WiZ Architectural Lighting Console"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "file": "File",
        "show_window": "Show window",
        "hide_window": "Hide window",
        "autostart": "Start with Windows",
        "exit": "Exit",
        "help": "Help",
        "shortcuts": "Keyboard shortcuts",
        "about": "About",
        "about_title": "About",
        "about_version": "Version",
        "about_license": "License",
        "about_license_unspecified": "Not specified",
    },
    "es": {
        "file": "Archivo",
        "show_window": "Mostrar ventana",
        "hide_window": "Ocultar ventana",
        "autostart": "Iniciar con Windows",
        "exit": "Salir",
        "help": "Ayuda",
        "shortcuts": "Atajos de teclado",
        "about": "Acerca de",
        "about_title": "Acerca de",
        "about_version": "Versión",
        "about_license": "Licencia",
        "about_license_unspecified": "No especificada",
    },
}


@dataclass(frozen=True)
class AppMenuItem:
    """A menu action, a separator or a checkable entry (`checked` is None when not checkable)."""

    label: str = ""
    action_id: str = ""
    checked: bool | None = None
    is_separator: bool = False


@dataclass(frozen=True)
class AppMenu:
    """A top-level menu with its items."""

    title: str
    items: tuple[AppMenuItem, ...]


def resolve_menu_strings(language: str) -> dict[str, str]:
    """Return the label dictionary for a language, falling back to English."""
    normalized = str(language or "en").strip().lower()
    return _STRINGS.get(normalized, _STRINGS["en"])


def build_app_menu(
    *,
    language: str = "en",
    window_visible: bool = True,
    autostart_enabled: bool = False,
) -> list[AppMenu]:
    """Build the File and Help menus for the current state and language."""
    s = resolve_menu_strings(language)
    return [
        AppMenu(
            title=s["file"],
            items=(
                AppMenuItem(
                    label=s["hide_window"] if window_visible else s["show_window"],
                    action_id=ACTION_TOGGLE_WINDOW,
                ),
                AppMenuItem(
                    label=s["autostart"],
                    action_id=ACTION_TOGGLE_AUTOSTART,
                    checked=autostart_enabled,
                ),
                AppMenuItem(is_separator=True),
                AppMenuItem(label=s["exit"], action_id=ACTION_EXIT),
            ),
        ),
        AppMenu(
            title=s["help"],
            items=(
                AppMenuItem(label=s["shortcuts"], action_id=ACTION_SHOW_SHORTCUTS),
                AppMenuItem(label=s["about"], action_id=ACTION_SHOW_ABOUT),
            ),
        ),
    ]


def build_about_text(language: str, version: str, license_name: str | None = None) -> str:
    """Compose the About dialog body."""
    s = resolve_menu_strings(language)
    license_text = license_name or s["about_license_unspecified"]
    return (
        f"{APP_DISPLAY_NAME}\n"
        f"{s['about_version']}: {version}\n"
        f"{s['about_license']}: {license_text}"
    )
