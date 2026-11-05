"""Tests for window auto-fit: pure height math, JsApi/WebviewBridge validation, 64-bit Win32 and InvokeRequired."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gestor_luces.adapters.ui_webview.bridge import JsApi
from gestor_luces.main import (
    WINDOW_MIN_SIZE,
    _compute_fit_height,
    _fit_native_window_height,
)


def test_compute_fit_height_applies_chrome() -> None:
    assert _compute_fit_height(620, 46.4, 640, 1000) == 666


def test_compute_fit_height_clamps_to_min_and_max() -> None:
    assert _compute_fit_height(100, 46, WINDOW_MIN_SIZE[1], 1000) == WINDOW_MIN_SIZE[1]
    assert _compute_fit_height(3000, 46, WINDOW_MIN_SIZE[1], 900) == 900
    assert _compute_fit_height(500, 46, WINDOW_MIN_SIZE[1], 400) == 400


def test_fit_window_height_without_callback_returns_not_ok() -> None:
    api = JsApi.__new__(JsApi)
    res = api.fit_window_height(500)
    assert res["ok"] is False


@pytest.mark.parametrize("value", [True, False, 500.0, "500", None, 199, 4001, -1])
def test_fit_window_height_rejects_invalid_values(value: object) -> None:
    calls: list[int] = []
    api = JsApi(MagicMock(), fit_window=lambda px: calls.append(px) or True)  # type: ignore[arg-type]
    res = api.fit_window_height(value)  # type: ignore[arg-type]
    assert res["ok"] is False
    assert calls == []


def test_fit_window_height_accepts_valid_int_and_calls_callback() -> None:
    calls: list[int] = []
    api = JsApi(MagicMock(), fit_window=lambda px: calls.append(px) or True)  # type: ignore[arg-type]
    assert api.fit_window_height(680) == {"ok": True}
    assert calls == [680]


def test_fit_window_height_swallows_callback_errors() -> None:
    def boom(_px: int) -> bool:
        raise RuntimeError("native failure")

    api = JsApi(MagicMock(), fit_window=boom)  # type: ignore[arg-type]
    res = api.fit_window_height(680)
    assert res["ok"] is False


def test_fit_native_window_height_handles_64bit_hwnd_and_invoke_required() -> None:
    hwnd_64 = 0x0000000240001111
    hmon_64 = 0x0000000390002222
    set_pos_calls: list[tuple[int, int, int, int, int, int, int]] = []
    invoked: list[bool] = []

    class FakeUser32:
        def IsZoomed(self, _hwnd: int) -> int:  # noqa: N802
            return 0

        def IsIconic(self, _hwnd: int) -> int:  # noqa: N802
            return 0

        def IsWindowVisible(self, _hwnd: int) -> int:  # noqa: N802
            return 1

        def GetDpiForWindow(self, _hwnd: int) -> int:  # noqa: N802
            return 96

        def GetWindowRect(self, _hwnd: int, rect_ptr: object) -> int:  # noqa: N802
            rect = ctypes.cast(rect_ptr, ctypes.POINTER(ctypes.wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = 100, 100, 720, 860
            return 1

        def GetClientRect(self, _hwnd: int, rect_ptr: object) -> int:  # noqa: N802
            rect = ctypes.cast(rect_ptr, ctypes.POINTER(ctypes.wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 620, 720
            return 1

        def MonitorFromWindow(self, _hwnd: int, _flags: int) -> int:  # noqa: N802
            return hmon_64

        def GetMonitorInfoW(self, monitor: int, info_ptr: object) -> int:  # noqa: N802
            assert monitor == hmon_64
            # Populate rcWork at offset 4 + 16 = 20 bytes (cbSize + rcMonitor)
            raw_ints = ctypes.cast(info_ptr, ctypes.POINTER(ctypes.c_long * 10)).contents
            raw_ints[5] = 0  # rcWork.left
            raw_ints[6] = 0  # rcWork.top
            raw_ints[7] = 1920  # rcWork.right
            raw_ints[8] = 1040  # rcWork.bottom
            return 1

        def SetWindowPos(  # noqa: N802
            self,
            hwnd: int,
            insert_after: int,
            x: int,
            y: int,
            cx: int,
            cy: int,
            flags: int,
        ) -> int:
            set_pos_calls.append((hwnd, insert_after, x, y, cx, cy, flags))
            return 1

    menu_strip = SimpleNamespace(
        GetType=lambda: SimpleNamespace(Name="MenuStrip"),
        Visible=True,
        Height=24,
    )

    def fake_invoke(action: object) -> None:
        invoked.append(True)
        if callable(action):
            action()
        elif hasattr(action, "Invoke"):
            action.Invoke()

    fake_window = SimpleNamespace(
        native=SimpleNamespace(
            IsDisposed=False,
            IsHandleCreated=True,
            InvokeRequired=True,
            Invoke=fake_invoke,
            Handle=SimpleNamespace(
                ToInt64=lambda: hwnd_64,
                ToInt32=lambda: (_ for _ in ()).throw(OverflowError("32-bit overflow")),
            ),
            Controls=[menu_strip],
        )
    )

    ok = _fit_native_window_height(
        fake_window,
        660,
        platform="win32",
        user32=FakeUser32(),
    )
    assert ok is True
    assert invoked == [True]
    # Chrome = (860 - 100) - 720 + 24 = 64; target = 660 + 64 = 724 (>= min 640)
    assert set_pos_calls == [(hwnd_64, 0, 100, 100, 620, 724, 0x0004 | 0x0010)]


def test_fit_native_window_height_skips_when_disposed_or_handle_not_created() -> None:
    disposed_window = SimpleNamespace(
        native=SimpleNamespace(IsDisposed=True, IsHandleCreated=True)
    )
    uncreated_window = SimpleNamespace(
        native=SimpleNamespace(IsDisposed=False, IsHandleCreated=False)
    )
    assert _fit_native_window_height(disposed_window, 700, platform="win32") is False
    assert _fit_native_window_height(uncreated_window, 700, platform="win32") is False


def test_scenes_grid_prevents_css_grid_row_collapse() -> None:
    from pathlib import Path
    import re

    styles_path = Path(__file__).resolve().parent.parent / "ui" / "styles.css"
    css_text = styles_path.read_text(encoding="utf-8")

    scenes_grid_match = re.search(r"\.scenes-grid\s*\{([^}]*)\}", css_text)
    assert scenes_grid_match is not None
    scenes_grid_body = scenes_grid_match.group(1)
    assert "grid-auto-rows: max-content" in scenes_grid_body
    assert "align-content: start" in scenes_grid_body

    scene_card_match = re.search(r"\.scene-card\s*\{([^}]*)\}", css_text)
    assert scene_card_match is not None
    scene_card_body = scene_card_match.group(1)
    assert "min-height: 58px" in scene_card_body
    assert "overflow: clip" in scene_card_body
    assert "overflow: hidden" not in scene_card_body

    custom_grid_match = re.search(r"\.custom-scenes-grid\s*\{([^}]*)\}", css_text)
    assert custom_grid_match is not None
    assert "grid-auto-rows: max-content" in custom_grid_match.group(1)

