"""Chrome de ventana Win32: atributo DWM de barra de titulo oscura y utilidades nativas.

Cada funcion acepta la DLL Win32 cruda (`dwmapi=`) como dependencia inyectable, de modo
que se puede probar sin una ventana real ni una sesion de escritorio.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from typing import Any

_LOGGER = logging.getLogger(__name__)
_WINDOW_ICON_LOCK = threading.Lock()
# Maps (hwnd, kind) -> (icon_path, hicon_handle, user32_id)
_APPLIED_WINDOW_ICONS: dict[tuple[int, int], tuple[str, int, int]] = {}

#: Unica politica de errores para las llamadas `ctypes` a una DLL de Win32 del paquete.
#:
#: Una llamada nativa solo puede fallar asi: la DLL o la funcion no estan (`OSError`,
#: `AttributeError` en versiones viejas de Windows), los argumentos no coinciden con la
#: firma declarada (`TypeError` y `ctypes.ArgumentError`), un `byref()`/puntero inutil
#: (`ValueError`) o el estado interno de ctypes (`RuntimeError`). Cualquier otra excepcion
#: es un defecto del programa y debe propagarse a quien pueda arreglarlo.
NATIVE_CALL_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    AttributeError,
    TypeError,
    ValueError,
    RuntimeError,
    ctypes.ArgumentError,
)


THEME_WINDOW_CHROME: dict[str, dict[str, Any]] = {
    "architectural-stone": {
        "background_color": "#F4F1EA",
        "dark_titlebar": False,
    },
    "atmospheric-dark": {
        "background_color": "#08090C",
        "dark_titlebar": True,
    },
}
DARK_TITLEBAR_ENABLED = False

#: Preferencia de esquinas de DWM (Windows 11+): atributo y valor de esquina redondeada.
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

#: Estilo extendido de ventana y su indice: una ventana visible con `WS_EX_TOOLWINDOW`
#: queda fuera del conmutador alt+tab y de la barra de tareas.
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080

#: Identidad propia de la aplicacion en la barra de tareas de Windows. Sin ella el proceso
#: hereda la identidad y el icono de `python.exe`: la barra agrupa las ventanas bajo el
#: interprete y muestra su logo aunque la ventana tenga otro icono.
APP_USER_MODEL_ID = "AlexisAcevedo.WizConsole"

WM_SETICON = 0x0080
WIN_ICON_SMALL = 0
WIN_ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
SM_CXICON = 11
SM_CYICON = 12
SM_CXSMICON = 49
SM_CYSMICON = 50


def _resolve_native_hwnd(native_form: Any) -> int | None:
    """Extrae el HWND nativo de 64 bits sin truncar punteros mayores a 0x7FFFFFFF."""
    if native_form is None:
        return None
    handle = getattr(native_form, "Handle", None)
    if handle is None:
        return None
    for method_name in ("ToInt64", "ToInt32"):
        converter = getattr(handle, method_name, None)
        if callable(converter):
            try:
                hwnd = int(converter())
                return hwnd if hwnd > 0 else None
            except (OverflowError, TypeError, ValueError):
                # `ToInt32` desborda en un handle de 64 bits: se prueba la conversion siguiente.
                _LOGGER.debug("Handle.%s() conversion failed.", method_name, exc_info=True)
    try:
        hwnd = int(handle)
        return hwnd if hwnd > 0 else None
    except (OverflowError, TypeError, ValueError):
        return None


def _configure_fn_signature(fn: Any, argtypes: list[Any], restype: Any) -> None:
    """Declara `argtypes` y `restype` sobre punteros Win32 reales sin romper dobles de prueba."""
    if fn is None:
        return
    try:
        if hasattr(fn, "argtypes"):
            fn.argtypes = argtypes
        if hasattr(fn, "restype"):
            fn.restype = restype
    except (AttributeError, TypeError):
        # Un puntero de ctypes solo rechaza la firma con `TypeError`; un doble de prueba
        # que expone los atributos pero no los acepta, con `AttributeError`.
        _LOGGER.debug("Win32 function signature setup skipped.", exc_info=True)


def apply_tool_window_style(
    window: Any,
    *,
    platform: str = sys.platform,
    user32: Any = None,
) -> bool:
    """Marca una ventana ya creada como ventana de herramienta (`WS_EX_TOOLWINDOW`).

    Es la unica forma fiable de sacar una ventana del conmutador alt+tab: `ShowInTaskbar
    = False` de WinForms quita el boton de la barra de tareas pero deja la ventana
    listada como candidata. El estilo debe existir con la ventana todavia oculta, porque
    el conmutador lo evalua al mostrarla; por eso se aplica sobre el handle recien creado
    y antes del bombeo de mensajes. Devuelve `True` solo si el estilo quedo aplicado, y
    nunca lanza: sin Win32, sin handle o sin las funciones necesarias informa `False`.
    """
    if platform != "win32":
        return False
    try:
        hwnd = _resolve_native_hwnd(window)
        if hwnd is None:
            return False
        import ctypes
        from ctypes import wintypes

        target_user32 = ctypes.windll.user32 if user32 is None else user32
        # `*WindowLongPtrW` existe en user32 de 64 bits; en uno de 32 bits el equivalente es
        # `*WindowLongW`. Se prefiere el de punteros para no truncar el estilo extendido.
        get_long = getattr(target_user32, "GetWindowLongPtrW", None)
        set_long = getattr(target_user32, "SetWindowLongPtrW", None)
        if get_long is None or set_long is None:
            get_long = getattr(target_user32, "GetWindowLongW", None)
            set_long = getattr(target_user32, "SetWindowLongW", None)
        if get_long is None or set_long is None:
            return False
        _configure_fn_signature(get_long, [wintypes.HWND, ctypes.c_int], ctypes.c_void_p)
        _configure_fn_signature(
            set_long,
            [wintypes.HWND, ctypes.c_int, ctypes.c_void_p],
            ctypes.c_void_p,
        )
        current = int(get_long(hwnd, GWL_EXSTYLE) or 0) & 0xFFFFFFFF
        if current & WS_EX_TOOLWINDOW:
            return True
        set_long(hwnd, GWL_EXSTYLE, current | WS_EX_TOOLWINDOW)
        return bool(int(get_long(hwnd, GWL_EXSTYLE) or 0) & WS_EX_TOOLWINDOW)
    except NATIVE_CALL_ERRORS:
        _LOGGER.debug("Windows tool window style skipped.", exc_info=True)
        return False


def apply_app_user_model_id(
    app_id: str = APP_USER_MODEL_ID,
    *,
    platform: str = sys.platform,
    shell32: Any = None,
) -> bool:
    """Da al proceso su identidad propia en la barra de tareas de Windows.

    Debe llamarse antes de crear la primera ventana: Windows decide con este identificador
    con que aplicacion agrupa el boton de la barra y de donde toma su icono. Sin el, correr
    desde el fuente agrupa la ventana bajo `python.exe` y la barra muestra el logo de Python
    aunque la ventana tenga el icono correcto. Nunca lanza: fuera de Windows o sin shell32
    devuelve `False`.
    """
    if platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        target_shell32 = ctypes.windll.shell32 if shell32 is None else shell32
        setter = getattr(target_shell32, "SetCurrentProcessExplicitAppUserModelID", None)
        if setter is None:
            return False
        _configure_fn_signature(setter, [wintypes.LPCWSTR], ctypes.c_long)
        return int(setter(str(app_id))) == 0
    except NATIVE_CALL_ERRORS:
        _LOGGER.debug("Explicit AppUserModelID skipped.", exc_info=True)
        return False


def _configure_icon_user32(target_user32: Any) -> tuple[Any, Any, Any, Any] | None:
    """Resolve and configure 64-bit Win32 signatures for window icon helpers."""
    import ctypes
    from ctypes import wintypes

    load = getattr(target_user32, "LoadImageW", None)
    send = getattr(target_user32, "SendMessageW", None)
    if load is None or send is None:
        return None
    metric = getattr(target_user32, "GetSystemMetrics", None)
    destroy = getattr(target_user32, "DestroyIcon", None)
    _configure_fn_signature(
        load,
        [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ],
        wintypes.HANDLE,
    )
    _configure_fn_signature(
        send,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
        ctypes.c_ssize_t,
    )
    _configure_fn_signature(metric, [ctypes.c_int], ctypes.c_int)
    _configure_fn_signature(destroy, [wintypes.HICON], wintypes.BOOL)
    return load, send, metric, destroy


def apply_window_icon(
    window: Any,
    icon_path: Any,
    *,
    platform: str = sys.platform,
    user32: Any = None,
) -> bool:
    """Fija el icono de la ventana con el `.ico` de la aplicacion, en ambos tamanos.

    `WM_SETICON` es lo que usan la barra de tareas, el conmutador alt+tab y el globo del
    icono: se aplican los dos tamanos (grande del sistema y chico de la barra) porque
    Windows los pide por separado y un fallo de uno no debe dejar al otro sin icono. Cachea
    los `HICON` aplicados por `(hwnd, tipo)` para no filtrar handles en llamadas repetidas
    y destruye el handle previo solo cuando se reemplaza por otro archivo. Nunca lanza; sin
    archivo, sin handle o fuera de Windows devuelve `False`.
    """
    if platform != "win32":
        return False
    path = str(icon_path)
    try:
        if not os.path.isfile(path):
            return False
        native_form = getattr(window, "native", None)
        hwnd = _resolve_native_hwnd(native_form if native_form is not None else window)
        if hwnd is None:
            return False
        import ctypes

        target_user32 = ctypes.windll.user32 if user32 is None else user32
        fns = _configure_icon_user32(target_user32)
        if fns is None:
            return False
        load, send, metric, destroy = fns
        user32_id = id(target_user32)
        applied = False
        for kind, (cx_index, cy_index) in (
            (WIN_ICON_BIG, (SM_CXICON, SM_CYICON)),
            (WIN_ICON_SMALL, (SM_CXSMICON, SM_CYSMICON)),
        ):
            with _WINDOW_ICON_LOCK:
                cached = _APPLIED_WINDOW_ICONS.get((hwnd, kind))
            if cached is not None and cached[0] == path and cached[2] == user32_id and cached[1]:
                send(hwnd, WM_SETICON, kind, cached[1])
                applied = True
                continue
            width = int(metric(cx_index)) if metric is not None else 0
            height = int(metric(cy_index)) if metric is not None else 0
            handle = load(None, path, IMAGE_ICON, width, height, LR_LOADFROMFILE)
            if not handle:
                # Sin medidas del sistema se pide el tamano por defecto del archivo.
                handle = load(None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if not handle:
                continue
            handle_int = int(handle)
            # `SendMessageW` devuelve el icono previo (0 la primera vez), asi que no sirve
            # como senal de exito: el icono quedo aplicado si el archivo cargo.
            send(hwnd, WM_SETICON, kind, handle_int)
            with _WINDOW_ICON_LOCK:
                previous = _APPLIED_WINDOW_ICONS.get((hwnd, kind))
                _APPLIED_WINDOW_ICONS[(hwnd, kind)] = (path, handle_int, user32_id)
            if (
                previous is not None
                and destroy is not None
                and previous[2] == user32_id
                and previous[1]
                and previous[1] != handle_int
            ):
                destroy(previous[1])
            applied = True
        return applied
    except NATIVE_CALL_ERRORS:
        _LOGGER.debug("Window icon skipped.", exc_info=True)
        return False


def release_window_icons(
    window: Any,
    *,
    platform: str = sys.platform,
    user32: Any = None,
) -> None:
    """Destruye los `HICON` cacheados asociados a la ventana al cerrarla."""
    if platform != "win32":
        return
    try:
        native_form = getattr(window, "native", None)
        hwnd = _resolve_native_hwnd(native_form if native_form is not None else window)
        if hwnd is None:
            return
        import ctypes
        from ctypes import wintypes

        target_user32 = ctypes.windll.user32 if user32 is None else user32
        destroy = getattr(target_user32, "DestroyIcon", None)
        if destroy is None:
            return
        _configure_fn_signature(destroy, [wintypes.HICON], wintypes.BOOL)
        user32_id = id(target_user32)
        with _WINDOW_ICON_LOCK:
            entries = [
                _APPLIED_WINDOW_ICONS.pop((hwnd, kind), None)
                for kind in (WIN_ICON_BIG, WIN_ICON_SMALL)
            ]
        for entry in entries:
            if entry is not None and entry[2] == user32_id and entry[1]:
                destroy(entry[1])
    except NATIVE_CALL_ERRORS:
        _LOGGER.debug("Window icon release skipped.", exc_info=True)


def _set_windows_dark_titlebar_attribute(
    window: Any,
    *,
    enabled: bool = DARK_TITLEBAR_ENABLED,
    platform: str = sys.platform,
    dwmapi: Any = None,
) -> bool:
    """Actualiza bidireccionalmente el atributo DWMWA_USE_IMMERSIVE_DARK_MODE (20) en Windows."""
    if platform != "win32":
        return False
    try:
        native_form = getattr(window, "native", None)
        hwnd = _resolve_native_hwnd(native_form)
        if hwnd is None:
            return False
        import ctypes
        from ctypes import wintypes

        target_dwmapi = ctypes.windll.dwmapi if dwmapi is None else dwmapi
        dwm_fn = getattr(target_dwmapi, "DwmSetWindowAttribute", None)
        if dwm_fn is None:
            return False
        _configure_fn_signature(
            dwm_fn,
            [wintypes.HWND, ctypes.c_int, ctypes.c_void_p, ctypes.c_int],
            ctypes.c_int,
        )
        value = ctypes.c_int(1 if enabled else 0)
        dwm_fn(
            hwnd,
            20,  # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.byref(value),
            ctypes.sizeof(ctypes.c_int),
        )
        return True
    except NATIVE_CALL_ERRORS:
        _LOGGER.debug("Windows dark titlebar attribute skipped.", exc_info=True)
        return False


def _apply_corner_preference(
    window: Any,
    *,
    preference: int = DWMWCP_ROUND,
    platform: str = sys.platform,
    dwmapi: Any = None,
) -> bool:
    """Pide a DWM esquinas redondeadas (`DWMWCP_ROUND`) para una ventana ya creada.

    El handle debe existir antes de la llamada: en un menu contextual eso ocurre recien
    cuando la ventana desplegable se muestra. Windows anteriores a 11 rechazan el
    atributo y se devuelve `False`; la vista WinForms aplica ademas su propia region
    redondeada recortada, que es la que garantiza las esquinas cuando DWM no redondea la
    ventana. Nunca lanza.
    """
    if platform != "win32":
        return False
    try:
        hwnd = _resolve_native_hwnd(window)
        if hwnd is None:
            return False
        import ctypes
        from ctypes import wintypes

        target_dwmapi = ctypes.windll.dwmapi if dwmapi is None else dwmapi
        dwm_fn = getattr(target_dwmapi, "DwmSetWindowAttribute", None)
        if dwm_fn is None:
            return False
        _configure_fn_signature(
            dwm_fn,
            [wintypes.HWND, ctypes.c_int, ctypes.c_void_p, ctypes.c_int],
            ctypes.c_int,
        )
        value = ctypes.c_int(preference)
        result = dwm_fn(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value),
            ctypes.sizeof(ctypes.c_int),
        )
        return int(result or 0) == 0
    except NATIVE_CALL_ERRORS:
        _LOGGER.debug("DWM corner preference skipped.", exc_info=True)
        return False
