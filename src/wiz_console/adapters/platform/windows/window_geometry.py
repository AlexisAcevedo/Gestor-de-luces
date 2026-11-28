"""Geometria de la ventana nativa: tamano inicial centrado y auto-ajuste al contenido.

La matematica pura (`_compute_initial_window_geometry`, `_compute_fit_height`) no toca
Win32; `_fit_native_window_height` acepta la DLL `user32` cruda como dependencia
inyectable para poder probarse sin una ventana real.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from wiz_console.adapters.platform.windows.window_chrome import (
    NATIVE_CALL_ERRORS,
    _configure_fn_signature,
    _resolve_native_hwnd,
)

_LOGGER = logging.getLogger(__name__)


WINDOW_DEFAULT_SIZE = (620, 760)
WINDOW_MIN_SIZE = (480, 640)
WINDOW_FALLBACK_SIZE = WINDOW_DEFAULT_SIZE
# El auto-fit no lleva la ventana mas alla de esta fraccion del area de trabajo: una
# seccion larga (la grilla de escenas pide ~1310 px) no debe ocupar toda la pantalla;
# lo que sobra scrollea en el escenario, nunca dentro de una grilla.
WINDOW_FIT_COMFORT_RATIO = 0.72


def _extract_screen_area(screen: Any) -> tuple[int, int, int, int] | None:
    """Extrae `(origin_x, origin_y, width, height)` logicos de una pantalla pywebview.

    Prefiere `screen.frame` (`WorkingArea`) cuando expone dimensiones validas para
    respetar la barra de tareas; si no, usa `(screen.x, screen.y, screen.width, screen.height)`.
    """
    try:
        frame = getattr(screen, "frame", None)
        if frame is not None:
            area_w = int(getattr(frame, "Width", 0))
            area_h = int(getattr(frame, "Height", 0))
            if area_w > 0 and area_h > 0:
                area_x = int(getattr(frame, "X", getattr(screen, "x", 0) or 0))
                area_y = int(getattr(frame, "Y", getattr(screen, "y", 0) or 0))
                return area_x, area_y, area_w, area_h
        screen_w = int(screen.width)
        screen_h = int(screen.height)
        origin_x = int(getattr(screen, "x", 0) or 0)
        origin_y = int(getattr(screen, "y", 0) or 0)
    except (AttributeError, LookupError, TypeError, ValueError, OverflowError):
        return None
    if screen_w <= 0 or screen_h <= 0:
        return None
    return origin_x, origin_y, screen_w, screen_h


def _select_primary_screen(screens: Any) -> Any:
    """Devuelve la pantalla principal (`(x, y) == (0, 0)`) o `screens[0]` como respaldo."""
    try:
        screen_list = list(screens)
    except TypeError:
        return None
    if not screen_list:
        return None
    for candidate in screen_list:
        try:
            if (
                int(getattr(candidate, "x", 0) or 0) == 0
                and int(getattr(candidate, "y", 0) or 0) == 0
            ):
                return candidate
        except (TypeError, ValueError, OverflowError):
            continue
    return screen_list[0]


def _compute_initial_window_geometry(
    webview_module: object,
) -> tuple[int, int, int | None, int | None]:
    """Return (width, height, x, y) sized to WINDOW_DEFAULT_SIZE, clamped to screen
    bounds, and centered.

    Falls back to WINDOW_DEFAULT_SIZE (OS-centered) when screen info is unavailable.
    """
    screens = getattr(webview_module, "screens", None)
    primary = _select_primary_screen(screens) if screens else None
    if primary is None:
        return (*WINDOW_DEFAULT_SIZE, None, None)
    area = _extract_screen_area(primary)
    if area is None:
        return (*WINDOW_DEFAULT_SIZE, None, None)
    origin_x, origin_y, screen_w, screen_h = area

    width = min(WINDOW_DEFAULT_SIZE[0], screen_w)
    if screen_w >= WINDOW_MIN_SIZE[0]:
        width = max(WINDOW_MIN_SIZE[0], width)

    height = min(WINDOW_DEFAULT_SIZE[1], screen_h)
    if screen_h >= WINDOW_MIN_SIZE[1]:
        height = max(WINDOW_MIN_SIZE[1], height)

    x = origin_x + max(0, (screen_w - width) // 2)
    y = origin_y + max(0, (screen_h - height) // 2)
    return width, height, x, y


def _fit_max_height(work_area_px: int, *, comfort_ratio: float = WINDOW_FIT_COMFORT_RATIO) -> int:
    """Altura maxima (logica) que el auto-fit puede pedir, como fraccion del area de trabajo.

    Deja aire alrededor de la ventana para que una seccion larga no llene la pantalla.
    """
    return max(1, int(work_area_px * comfort_ratio))


def _compute_fit_height(
    content_px: int,
    chrome: float,
    min_h: int = WINDOW_MIN_SIZE[1],
    max_h: int = WINDOW_DEFAULT_SIZE[1],
) -> int:
    """Return the outer window height (logical px) for a page content height.

    `chrome` is the non-client height (title bar + menu bar). The result is clamped to
    `[min_h, max_h]`; when the work area is smaller than `min_h`, the work area wins.
    """
    target = int(round(content_px + chrome))
    return max(1, min(max(target, int(min_h)), int(max_h)))


def _fit_native_window_height(
    window: Any,
    content_px: int,
    fallback_max_h: int | None = None,
    *,
    baseline_height: int = WINDOW_DEFAULT_SIZE[1],
    min_height: int = WINDOW_MIN_SIZE[1],
    platform: str = sys.platform,
    user32: Any = None,
) -> bool:
    """Resize the native window so its client height equals `content_px` CSS pixels.

    Keeps x, y and width fixed (moves the window up only when the new bottom would leave
    the monitor work area). Marshals inspection onto the WinForms UI thread when
    `InvokeRequired` is True and guards against disposed or uncreated handles.
    """
    if platform != "win32":
        return False
    native_form = getattr(window, "native", None)
    if native_form is None:
        return False
    if (
        bool(getattr(native_form, "IsDisposed", False))
        or bool(getattr(native_form, "Disposing", False))
        or not bool(getattr(native_form, "IsHandleCreated", True))
    ):
        return False

    def _execute() -> bool:
        if (
            bool(getattr(native_form, "IsDisposed", False))
            or bool(getattr(native_form, "Disposing", False))
            or not bool(getattr(native_form, "IsHandleCreated", True))
        ):
            return False
        import ctypes
        from ctypes import wintypes

        hwnd = _resolve_native_hwnd(native_form)
        if hwnd is None:
            return False
        target_user32 = ctypes.windll.user32 if user32 is None else user32

        class _MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        _configure_fn_signature(
            getattr(target_user32, "IsZoomed", None),
            [wintypes.HWND],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "IsIconic", None),
            [wintypes.HWND],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "IsWindowVisible", None),
            [wintypes.HWND],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "GetDpiForWindow", None),
            [wintypes.HWND],
            wintypes.UINT,
        )
        _configure_fn_signature(
            getattr(target_user32, "GetWindowRect", None),
            [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "GetClientRect", None),
            [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "MonitorFromWindow", None),
            [wintypes.HWND, wintypes.DWORD],
            wintypes.HMONITOR,
        )
        _configure_fn_signature(
            getattr(target_user32, "GetMonitorInfoW", None),
            [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)],
            wintypes.BOOL,
        )
        _configure_fn_signature(
            getattr(target_user32, "SetWindowPos", None),
            [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ],
            wintypes.BOOL,
        )

        if (
            target_user32.IsZoomed(hwnd)
            or target_user32.IsIconic(hwnd)
            or not target_user32.IsWindowVisible(hwnd)
        ):
            return False

        try:
            raw_dpi = int(target_user32.GetDpiForWindow(hwnd))
            dpi = raw_dpi if raw_dpi > 0 else 96
        except NATIVE_CALL_ERRORS:
            # `GetDpiForWindow` no existe antes de Windows 10 1607: se asume 96 dpi.
            _LOGGER.debug("DPI query failed; assuming 96 dpi.", exc_info=True)
            dpi = 96
        scale = dpi / 96.0

        outer = wintypes.RECT()
        client = wintypes.RECT()
        if not target_user32.GetWindowRect(
            hwnd, ctypes.byref(outer)
        ) or not target_user32.GetClientRect(hwnd, ctypes.byref(client)):
            return False
        outer_h = outer.bottom - outer.top
        chrome_phys = outer_h - (client.bottom - client.top)
        try:
            controls = getattr(native_form, "Controls", None)
            if controls is not None:
                for control in list(controls):
                    if control.GetType().Name == "MenuStrip" and getattr(control, "Visible", True):
                        chrome_phys += int(control.Height)
        except (AttributeError, TypeError, ValueError):
            # Un control sin `GetType`/`Height` utilizable deja el chrome medido hasta aca;
            # una excepcion de pythonnet fuera de esta tupla la atrapa la frontera de abajo,
            # que solo cancela el ajuste (nunca tumba la app).
            _LOGGER.debug("Menu strip height query failed.", exc_info=True)

        work_top = None
        work_bottom = None
        try:
            monitor = target_user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            if monitor and target_user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work_top, work_bottom = info.rcWork.top, info.rcWork.bottom
        except NATIVE_CALL_ERRORS:
            # Sin area de trabajo se cae al tope de respaldo (`fallback_max_h`).
            _LOGGER.debug("Monitor work area query failed.", exc_info=True)
        if work_top is None or work_bottom is None:
            effective_fallback = fallback_max_h if fallback_max_h else baseline_height
            if not effective_fallback:
                return False
            work_top, work_bottom = outer.top, outer.top + int(effective_fallback * scale)

        work_height_phys = work_bottom - work_top
        if work_height_phys <= 0:
            return False

        target_logical = _compute_fit_height(
            content_px,
            chrome_phys / scale,
            min_height,
            _fit_max_height(int(work_height_phys / scale)),
        )
        target_phys = int(round(target_logical * scale))
        new_top = outer.top
        if new_top + target_phys > work_bottom:
            new_top = max(work_top, work_bottom - target_phys)
        elif new_top < work_top:
            new_top = work_top
        if target_phys == outer_h and new_top == outer.top:
            return True
        # SWP_NOZORDER | SWP_NOACTIVATE
        return bool(
            target_user32.SetWindowPos(
                hwnd,
                0,
                outer.left,
                new_top,
                outer.right - outer.left,
                target_phys,
                0x0004 | 0x0010,
            )
        )

    try:
        if bool(getattr(native_form, "InvokeRequired", False)):
            outcome = {"ok": False}

            def _marshaled() -> None:
                outcome["ok"] = _execute()

            invoke_fn = getattr(native_form, "Invoke", None)
            if not callable(invoke_fn):
                return False
            try:
                from System import Action

                invoke_fn(Action(_marshaled))
            except ImportError:
                invoke_fn(_marshaled)
            return outcome["ok"]
        return _execute()
    # FRONTERA: `_execute` corre sobre ctypes y, por `Invoke`, sobre el hilo de interfaz de
    # WinForms (pythonnet no garantiza el tipo de excepcion del CLR). Un auto-ajuste que
    # falla solo deja la ventana en su tamano actual; nunca debe tumbar al llamador.
    except Exception:
        _LOGGER.debug("Window fit skipped.", exc_info=True)
        return False
