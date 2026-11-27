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
APP_DISPLAY_NAME_ES = "Consola de Iluminación Arquitectónica WiZ"

#: Metadatos que el cuadro "Acerca de" informa. Es la unica fuente del paquete para estos
#: datos: `pyproject.toml` los declara para el empaquetado y aqui se repiten porque un
#: build congelado (PyInstaller) no lleva `pyproject.toml` ni metadatos de `importlib`, y el
#: dialogo no puede depender de la suerte del entorno para mostrar la licencia o el autor.
APP_LICENSE = "MIT"
APP_AUTHOR = "AlexisAcevedo"
APP_REPOSITORY = "https://github.com/AlexisAcevedo/wiz-architectural-lighting-console"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app_name": APP_DISPLAY_NAME,
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
        "about_author": "Author",
        "about_repository": "Repository",
    },
    "es": {
        "app_name": APP_DISPLAY_NAME_ES,
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
        "about_author": "Autor",
        "about_repository": "Repositorio",
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


def build_about_title(language: str) -> str:
    """Devuelve el titulo localizado del cuadro 'Acerca de' ('About' o 'Acerca de')."""
    return resolve_menu_strings(language)["about_title"]


def build_window_title(language: str) -> str:
    """Return the localized main window title."""
    return resolve_menu_strings(language)["app_name"]


def build_about_text(
    language: str,
    version: str,
    license_name: str | None = None,
    *,
    author: str = APP_AUTHOR,
    repository: str = APP_REPOSITORY,
) -> str:
    """Compone el cuerpo del cuadro "Acerca de" con los metadatos reales del paquete.

    Ningun campo queda vacio: un `license_name` vacio cae a la licencia declarada del
    proyecto en vez de mostrar un marcador de posicion.
    """
    s = resolve_menu_strings(language)
    return "\n".join(
        (
            s["app_name"],
            f"{s['about_version']}: {version}",
            f"{s['about_license']}: {license_name or APP_LICENSE}",
            f"{s['about_author']}: {author}",
            f"{s['about_repository']}: {repository}",
        )
    )
