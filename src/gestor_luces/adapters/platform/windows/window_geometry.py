"""Geometria de la ventana nativa: tamano inicial centrado y auto-ajuste al contenido.

La matematica pura (`_compute_initial_window_geometry`, `_compute_fit_height`) no toca
Win32; `_fit_native_window_height` acepta la DLL `user32` cruda como dependencia
inyectable para poder probarse sin una ventana real.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from gestor_luces.adapters.platform.windows.window_chrome import (
    _configure_fn_signature,
    _resolve_native_hwnd,
)

_LOGGER = logging.getLogger(__name__)


WINDOW_DEFAULT_SIZE = (620, 760)
WINDOW_MIN_SIZE = (480, 640)
WINDOW_FALLBACK_SIZE = WINDOW_DEFAULT_SIZE


def _compute_initial_window_geometry(
    webview_module: object,
) -> tuple[int, int, int | None, int | None]:
    """Return (width, height, x, y) sized to WINDOW_DEFAULT_SIZE, clamped to screen
    bounds, and centered.

    Falls back to WINDOW_DEFAULT_SIZE (OS-centered) when screen info is unavailable.
    """
    try:
        screens = getattr(webview_module, "screens", None)
        if not screens:
            raise RuntimeError("no screens reported")
        screen = screens[0]
        screen_w, screen_h = int(screen.width), int(screen.height)
        if screen_w <= 0 or screen_h <= 0:
            raise RuntimeError("invalid screen size")
    except Exception:
        return (*WINDOW_DEFAULT_SIZE, None, None)

    width = min(WINDOW_DEFAULT_SIZE[0], screen_w)
    if screen_w >= WINDOW_MIN_SIZE[0]:
        width = max(WINDOW_MIN_SIZE[0], width)

    height = min(WINDOW_DEFAULT_SIZE[1], screen_h)
    if screen_h >= WINDOW_MIN_SIZE[1]:
        height = max(WINDOW_MIN_SIZE[1], height)

    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    return width, height, x, y


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
    if bool(getattr(native_form, "IsDisposed", False)) or not bool(
        getattr(native_form, "IsHandleCreated", True)
    ):
        return False

    def _execute() -> bool:
        if bool(getattr(native_form, "IsDisposed", False)) or not bool(
            getattr(native_form, "IsHandleCreated", True)
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
            dpi = int(target_user32.GetDpiForWindow(hwnd)) or 96
        except Exception:
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
            for control in getattr(native_form, "Controls", ()):
                if control.GetType().Name == "MenuStrip" and getattr(control, "Visible", True):
                    chrome_phys += int(control.Height)
        except Exception:
            _LOGGER.debug("Menu strip height query failed.", exc_info=True)

        work_top = None
        work_bottom = None
        try:
            monitor = target_user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            if monitor and target_user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work_top, work_bottom = info.rcWork.top, info.rcWork.bottom
        except Exception:
            _LOGGER.debug("Monitor work area query failed.")
        if work_top is None or work_bottom is None:
            effective_fallback = fallback_max_h if fallback_max_h else baseline_height
            if not effective_fallback:
                return False
            work_top, work_bottom = outer.top, outer.top + int(effective_fallback * scale)

        target_logical = _compute_fit_height(
            content_px,
            chrome_phys / scale,
            min_height,
            int((work_bottom - work_top) / scale),
        )
        target_phys = int(round(target_logical * scale))
        if target_phys == outer_h:
            return True
        new_top = outer.top
        if new_top + target_phys > work_bottom:
            new_top = max(work_top, work_bottom - target_phys)
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

    if bool(getattr(native_form, "InvokeRequired", False)):
        outcome = {"ok": False}

        def _marshaled() -> None:
            outcome["ok"] = _execute()

        try:
            invoke_fn = getattr(native_form, "Invoke", None)
            if not callable(invoke_fn):
                return False
            try:
                from System import Action

                invoke_fn(Action(_marshaled))
            except ImportError:
                invoke_fn(_marshaled)
            return outcome["ok"]
        except Exception:
            _LOGGER.debug("Marshaled window fit skipped.", exc_info=True)
            return False

    try:
        return _execute()
    except Exception:
        _LOGGER.debug("Window fit skipped.", exc_info=True)
        return False
