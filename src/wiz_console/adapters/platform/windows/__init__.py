"""Capa de plataforma Windows (Win32/WinForms) con dependencias `ctypes` inyectables.

Reexporta los puentes nativos que antes vivian en `main.py` para que el punto de entrada
y las pruebas interactuen con una interfaz unica sin acoplarse a la organizacion interna
de los modulos.
"""

from __future__ import annotations

from wiz_console.adapters.platform.windows.foreground import _activate_window_foreground
from wiz_console.adapters.platform.windows.menu_state import (
    GUI_INMENUMODE,
    GUI_POPUPMENUMODE,
    GUI_SYSTEMMENUMODE,
    _is_menu_open,
)
from wiz_console.adapters.platform.windows.menu_sync import (
    _sync_native_menu,
    _sync_native_menu_theme,
    _to_webview_menus,
)
from wiz_console.adapters.platform.windows.message import show_message_box
from wiz_console.adapters.platform.windows.window_chrome import (
    APP_USER_MODEL_ID,
    DARK_TITLEBAR_ENABLED,
    THEME_WINDOW_CHROME,
    _configure_fn_signature,
    _resolve_native_hwnd,
    _set_windows_dark_titlebar_attribute,
    apply_app_user_model_id,
    apply_window_icon,
)
from wiz_console.adapters.platform.windows.window_geometry import (
    WINDOW_DEFAULT_SIZE,
    WINDOW_FALLBACK_SIZE,
    WINDOW_FIT_COMFORT_RATIO,
    WINDOW_MIN_SIZE,
    _compute_fit_height,
    _compute_initial_window_geometry,
    _fit_max_height,
    _fit_native_window_height,
)

__all__ = [
    "APP_USER_MODEL_ID",
    "DARK_TITLEBAR_ENABLED",
    "GUI_INMENUMODE",
    "GUI_POPUPMENUMODE",
    "GUI_SYSTEMMENUMODE",
    "THEME_WINDOW_CHROME",
    "WINDOW_DEFAULT_SIZE",
    "WINDOW_FIT_COMFORT_RATIO",
    "WINDOW_FALLBACK_SIZE",
    "WINDOW_MIN_SIZE",
    "_activate_window_foreground",
    "_compute_fit_height",
    "_compute_initial_window_geometry",
    "_configure_fn_signature",
    "_fit_max_height",
    "_fit_native_window_height",
    "_is_menu_open",
    "_resolve_native_hwnd",
    "_set_windows_dark_titlebar_attribute",
    "_sync_native_menu",
    "_sync_native_menu_theme",
    "_to_webview_menus",
    "apply_app_user_model_id",
    "apply_window_icon",
    "show_message_box",
]
