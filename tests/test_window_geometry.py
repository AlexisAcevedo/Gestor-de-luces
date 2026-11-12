"""Tests for initial desktop window geometry calculation, multi-theme chrome, and DWM 64-bit
safety."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace

from gestor_luces.main import (
    DARK_TITLEBAR_ENABLED,
    THEME_WINDOW_CHROME,
    WINDOW_DEFAULT_SIZE,
    WINDOW_FALLBACK_SIZE,
    WINDOW_MIN_SIZE,
    _activate_window_foreground,
    _compute_initial_window_geometry,
    _resolve_native_hwnd,
    _set_windows_dark_titlebar_attribute,
)


def test_window_geometry_constants_define_compact_controller() -> None:
    assert WINDOW_DEFAULT_SIZE == (620, 760)
    assert WINDOW_MIN_SIZE == (480, 640)
    assert WINDOW_FALLBACK_SIZE == WINDOW_DEFAULT_SIZE
    assert DARK_TITLEBAR_ENABLED is False
    assert THEME_WINDOW_CHROME == {
        "architectural-stone": {
            "background_color": "#F4F1EA",
            "dark_titlebar": False,
        },
        "atmospheric-dark": {
            "background_color": "#08090C",
            "dark_titlebar": True,
        },
    }


def test_set_windows_dark_titlebar_attribute_bidirectional_and_64bit_safe() -> None:
    calls: list[tuple[int, int, int, int]] = []

    class FakeDwmapi:
        def DwmSetWindowAttribute(  # noqa: N802
            self,
            hwnd: int,
            attr: int,
            val_ptr: object,
            size: int,
        ) -> int:
            raw_val = ctypes.cast(val_ptr, ctypes.POINTER(ctypes.c_int)).contents.value
            calls.append((hwnd, attr, raw_val, size))
            return 0

    hwnd_64 = 0x0000000180004242
    fake_window = SimpleNamespace(
        native=SimpleNamespace(
            Handle=SimpleNamespace(
                ToInt64=lambda: hwnd_64,
                ToInt32=lambda: (_ for _ in ()).throw(OverflowError("32-bit overflow")),
            )
        )
    )
    fake_dwmapi = FakeDwmapi()

    assert _resolve_native_hwnd(fake_window.native) == hwnd_64

    # Enabled=True sets DWM attribute 20 to 1
    assert (
        _set_windows_dark_titlebar_attribute(
            fake_window,
            enabled=True,
            platform="win32",
            dwmapi=fake_dwmapi,
        )
        is True
    )
    # Enabled=False sets DWM attribute 20 back to 0 (never early-returns)
    assert (
        _set_windows_dark_titlebar_attribute(
            fake_window,
            enabled=False,
            platform="win32",
            dwmapi=fake_dwmapi,
        )
        is True
    )
    assert calls == [
        (hwnd_64, 20, 1, ctypes.sizeof(ctypes.c_int)),
        (hwnd_64, 20, 0, ctypes.sizeof(ctypes.c_int)),
    ]

    # Non-win32 platforms safely skip
    assert (
        _set_windows_dark_titlebar_attribute(
            fake_window,
            enabled=True,
            platform="linux",
            dwmapi=fake_dwmapi,
        )
        is False
    )


def test_compute_initial_window_geometry_centers_on_standard_screen() -> None:
    fake_webview = SimpleNamespace(screens=[SimpleNamespace(width=1920, height=1080)])
    width, height, x, y = _compute_initial_window_geometry(fake_webview)
    assert (width, height) == (620, 760)
    assert x == (1920 - 620) // 2
    assert y == (1080 - 760) // 2


def test_compute_initial_window_geometry_clamps_to_small_screen() -> None:
    fake_webview = SimpleNamespace(screens=[SimpleNamespace(width=500, height=700)])
    width, height, x, y = _compute_initial_window_geometry(fake_webview)
    assert (width, height) == (500, 700)
    assert (x, y) == (0, 0)


def test_compute_initial_window_geometry_clamps_below_min_when_screen_tiny() -> None:
    fake_webview = SimpleNamespace(screens=[SimpleNamespace(width=400, height=500)])
    width, height, x, y = _compute_initial_window_geometry(fake_webview)
    assert (width, height) == (400, 500)
    assert (x, y) == (0, 0)


def test_compute_initial_window_geometry_falls_back_when_screens_missing() -> None:
    assert _compute_initial_window_geometry(SimpleNamespace(screens=[])) == (
        620,
        760,
        None,
        None,
    )
    assert _compute_initial_window_geometry(object()) == (620, 760, None, None)
    assert _compute_initial_window_geometry(
        SimpleNamespace(screens=[SimpleNamespace(width=0, height=-10)])
    ) == (620, 760, None, None)


def test_activate_window_foreground_skips_non_win32_and_missing_native() -> None:
    """`_activate_window_foreground` es no-op fuera de Windows y sin ventana nativa."""
    fake_window = SimpleNamespace(native=SimpleNamespace(Handle=SimpleNamespace()))
    assert _activate_window_foreground(fake_window, platform="linux") is False
    assert _activate_window_foreground(SimpleNamespace(native=None), platform="win32") is False


def test_activate_window_foreground_restores_and_raises(monkeypatch) -> None:
    """`_activate_window_foreground` llama ShowWindow/SetWindowPos/SetForegroundWindow."""
    import ctypes

    hwnd_64 = 0x0000000180007777
    show_calls: list[tuple[int, int]] = []
    pos_calls: list[tuple[int, int, int, int, int, int, int]] = []
    fg_calls: list[int] = []

    class _FakeFn:
        def __init__(self, sink) -> None:
            self._sink = sink
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            self._sink.append(args)
            return 1

    class FakeUser32:
        def __init__(self) -> None:
            self.ShowWindow = _FakeFn(show_calls)  # noqa: N802
            self.SetWindowPos = _FakeFn(pos_calls)  # noqa: N802
            self.SetForegroundWindow = _FakeFn(fg_calls)  # noqa: N802

    fake_user32 = FakeUser32()

    class FakeWindll:
        user32 = fake_user32

    # Inyectamos el fake en ctypes.windll (existe solo en Windows).
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)

    fake_window = SimpleNamespace(
        native=SimpleNamespace(
            Handle=SimpleNamespace(
                ToInt64=lambda: hwnd_64,
                ToInt32=lambda: (_ for _ in ()).throw(OverflowError("32-bit overflow")),
            )
        )
    )

    assert _activate_window_foreground(fake_window, platform="win32") is True

    # ShowWindow(hwnd, 9) + dos SetWindowPos + SetForegroundWindow
    assert show_calls == [(hwnd_64, 9)]
    assert pos_calls == [
        (hwnd_64, -1, 0, 0, 0, 0, 0x0001 | 0x0002),
        (hwnd_64, -2, 0, 0, 0, 0, 0x0001 | 0x0002),
    ]
    assert fg_calls == [(hwnd_64,)]
