"""Regression tests for Stage 4b: desktop shell concurrency, lifecycle, tray, and geometry."""

from __future__ import annotations

import ast
import asyncio
import ctypes
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.waits import POLL_SECONDS
from wiz_console import main as main_module
from wiz_console.adapters.platform.windows.window_geometry import (
    _compute_initial_window_geometry,
    _fit_native_window_height,
)
from wiz_console.adapters.tray.tray_icon import (
    ICON_THREAD_NAME,
    REFRESH_THREAD_NAME,
    TrayController,
)
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.desktop import app as desktop_app
from wiz_console.desktop.app import DesktopApplication


def _wait_until(predicate: Callable[[], bool], description: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"{description} (within {timeout}s)")


class _FakeEvent:
    def __init__(self) -> None:
        self.handlers: list[Callable[..., Any]] = []

    def __iadd__(self, handler: Callable[..., Any]) -> _FakeEvent:
        self.handlers.append(handler)
        return self


class _FakeWindowEvents:
    def __init__(self) -> None:
        self.shown = _FakeEvent()
        self.closing = _FakeEvent()
        self.minimized = _FakeEvent()
        self.closed = _FakeEvent()


class _FakeWindow:
    def __init__(self) -> None:
        self.events = _FakeWindowEvents()
        self.show_calls = 0
        self.hide_calls = 0
        self.destroy_calls = 0
        self.exposed: list[Callable[..., Any]] = []
        self.native = SimpleNamespace(
            IsDisposed=False,
            Disposing=False,
            IsHandleCreated=True,
        )

    def show(self) -> None:
        self.show_calls += 1

    def hide(self) -> None:
        self.hide_calls += 1

    def restore(self) -> None:
        return None

    def evaluate_js(self, _script: str) -> None:
        return None

    def expose(self, *functions: Callable[..., Any]) -> None:
        self.exposed.extend(functions)

    def destroy(self) -> None:
        self.destroy_calls += 1


class _FakeWebview:
    def __init__(self, screens: list[Any] | None = None) -> None:
        self.screens = (
            screens if screens is not None else [SimpleNamespace(width=1920, height=1080)]
        )
        self.create_calls: list[dict[str, Any]] = []
        self.window: _FakeWindow | None = None

    def create_window(self, **kwargs: Any) -> _FakeWindow:
        self.create_calls.append(kwargs)
        self.window = _FakeWindow()
        return self.window

    def start(self, **_kwargs: Any) -> None:
        return None


class _FakeBridge:
    def __init__(self, *, language: str = "en", theme: str = "architectural-stone") -> None:
        self.language = language
        self.theme = theme
        self.autostart_enabled = False
        self.get_autostart_calls = 0
        self.shutdown_calls = 0
        self.listener: Callable[[], None] | None = None

    def set_fit_window_callback(self, _cb: Callable[[int], bool]) -> None:
        return None

    def set_state_change_listener(self, listener: Callable[[], None] | None) -> None:
        self.listener = listener

    def get_tray_snapshot(self) -> dict[str, Any]:
        return {
            "is_on": False,
            "brightness": 100,
            "presets": [],
            "language": self.language,
            "theme": self.theme,
            "sleep_timer_active": False,
        }

    def get_autostart(self) -> dict[str, Any]:
        self.get_autostart_calls += 1
        return {"ok": True, "enabled": self.autostart_enabled}

    def set_autostart(self, enabled: bool) -> dict[str, Any]:
        self.autostart_enabled = enabled
        return {"ok": True, "enabled": enabled}

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeService:
    def __init__(self, *, language: str = "en", theme: str = "architectural-stone") -> None:
        self.language = language
        self.theme = theme

    def get_language(self) -> str:
        return self.language

    def get_theme(self) -> str:
        return self.theme


class _RecordingTrayView:
    def __init__(self) -> None:
        self._stopped = threading.Event()
        self.stop_calls = 0

    def run(self) -> None:
        self._stopped.wait(timeout=5.0)

    def stop(self) -> None:
        self.stop_calls += 1
        self._stopped.set()

    def apply(self, *_args: Any) -> None:
        return None


# --- DesktopApplication concurrency, menu/titlebar suppression, and icon release ---


def test_on_state_changed_skips_menu_and_titlebar_sync_on_light_drags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    titlebar_calls: list[bool] = []
    menu_sync_calls: list[list[Any]] = []
    monkeypatch.setattr(
        desktop_app,
        "_set_windows_dark_titlebar_attribute",
        lambda _win, *, enabled: titlebar_calls.append(enabled) or True,
    )
    monkeypatch.setattr(
        desktop_app,
        "_sync_native_menu",
        lambda _win, spec: menu_sync_calls.append(spec),
    )

    service = _FakeService(language="en", theme="architectural-stone")
    bridge = _FakeBridge(language="en", theme="architectural-stone")
    webview = _FakeWebview()
    app = DesktopApplication(
        service=service,  # type: ignore[arg-type]
        bridge=bridge,  # type: ignore[arg-type]
        index_path=tmp_path / "index.html",
        icon_path=tmp_path / "app.ico",
        ui_dir=tmp_path,
        webview_module=webview,
    )
    app.create_window()

    sync_requests = 0
    original_request = app.request_menu_sync

    def counting_request() -> None:
        nonlocal sync_requests
        sync_requests += 1
        original_request()

    monkeypatch.setattr(app, "request_menu_sync", counting_request)

    # First state change applies initial titlebar once, never requests menu sync.
    app.on_state_changed()
    assert titlebar_calls == [False]
    assert sync_requests == 0
    assert bridge.get_autostart_calls == 0

    # Subsequent light-drag notifications must not call DWM titlebar or menu sync.
    for _ in range(10):
        app.on_state_changed()
    assert len(titlebar_calls) == 1
    assert sync_requests == 0
    assert bridge.get_autostart_calls == 0

    # Changing theme triggers DWM titlebar update once; changing language triggers menu sync.
    service.theme = "atmospheric-dark"
    bridge.theme = "atmospheric-dark"
    app.on_state_changed()
    assert titlebar_calls == [False, True]
    assert sync_requests == 0

    service.language = "es"
    bridge.language = "es"
    app.on_state_changed()
    assert sync_requests == 1

    service.language = "es"
    app.on_state_changed()
    assert sync_requests == 1


def test_stale_hide_on_close_or_minimize_does_not_hide_after_show_or_quit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        desktop_app, "_set_windows_dark_titlebar_attribute", lambda *_a, **_kw: True
    )
    monkeypatch.setattr(desktop_app, "_activate_window_foreground", lambda *_a, **_kw: True)

    service = _FakeService()
    bridge = _FakeBridge()
    webview = _FakeWebview()
    app = DesktopApplication(
        service=service,  # type: ignore[arg-type]
        bridge=bridge,  # type: ignore[arg-type]
        index_path=tmp_path / "index.html",
        icon_path=tmp_path / "app.ico",
        ui_dir=tmp_path,
        webview_module=webview,
    )
    window = app.create_window()

    started_threads: list[threading.Thread] = []
    real_thread = threading.Thread

    def capture_thread(*args: Any, **kwargs: Any) -> threading.Thread:
        thread = real_thread(*args, **kwargs)
        started_threads.append(thread)
        return thread

    # Delay _apply_hide gate via _visibility_generation by changing generation before running.
    app._visibility_generation = 5
    app._hide_if_generation(4)
    assert window.hide_calls == 0
    assert app.is_window_visible is True

    # Simulate show_window() beating a queued on_closing() worker.
    gate = threading.Event()
    entered = threading.Event()
    original_hide = window.hide

    def slow_hide() -> None:
        original_hide()

    window.hide = slow_hide  # type: ignore[method-assign]

    def blocking_thread(*args: Any, **kwargs: Any) -> threading.Thread:
        target = kwargs["target"]
        target_args = kwargs.get("args", ())

        def wrapper() -> None:
            entered.set()
            gate.wait(timeout=2.0)
            target(*target_args)

        t = real_thread(target=wrapper, name=kwargs.get("name"), daemon=True)
        started_threads.append(t)
        return t

    monkeypatch.setattr(desktop_app.threading, "Thread", blocking_thread)
    assert app.on_closing() is False
    assert entered.wait(timeout=2.0)
    app.show_window()
    gate.set()
    for t in started_threads:
        t.join(timeout=2.0)

    assert window.hide_calls == 0
    assert app.is_window_visible is True


def test_on_closed_and_cleanup_release_window_icons_and_stop_menu_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desktop_app, "resolve_default_data_dir", lambda: tmp_path)
    monkeypatch.setattr(desktop_app, "create_tray_view", lambda _d: _RecordingTrayView())

    released_windows: list[Any] = []
    monkeypatch.setattr(
        desktop_app.window_chrome,
        "release_window_icons",
        lambda win: released_windows.append(win),
        raising=False,
    )

    service = _FakeService()
    bridge = _FakeBridge()
    webview = _FakeWebview()
    app = DesktopApplication(
        service=service,  # type: ignore[arg-type]
        bridge=bridge,  # type: ignore[arg-type]
        index_path=tmp_path / "index.html",
        icon_path=tmp_path / "app.ico",
        ui_dir=tmp_path,
        webview_module=webview,
    )
    window = app.create_window()
    app.start()

    assert app.is_quitting is True
    assert window in released_windows
    assert bridge.shutdown_calls >= 1

    released_windows.clear()
    app.on_closed()
    assert released_windows == [window]


def test_create_window_clamps_min_size_to_small_screen(tmp_path: Path) -> None:
    small_webview = _FakeWebview(screens=[SimpleNamespace(width=400, height=500)])
    app = DesktopApplication(
        service=_FakeService(),  # type: ignore[arg-type]
        bridge=_FakeBridge(),  # type: ignore[arg-type]
        index_path=tmp_path / "index.html",
        icon_path=tmp_path / "app.ico",
        ui_dir=tmp_path,
        webview_module=small_webview,
    )
    app.create_window()
    call = small_webview.create_calls[0]
    assert (call["width"], call["height"]) == (400, 500)
    assert call["min_size"] == (400, 500)


def test_desktop_app_uses_port_and_dead_interfaces_module_removed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert not (repo_root / "src" / "wiz_console" / "ports" / "interfaces.py").exists()

    app_py = repo_root / "src" / "wiz_console" / "desktop" / "app.py"
    tree = ast.parse(app_py.read_text(encoding="utf-8"), filename=str(app_py))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("wiz_console.application")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("wiz_console.application")


# --- BridgeLifecycle shutdown races & timed-out future cancellation ---


def test_bridge_run_async_cancels_timed_out_task() -> None:
    bridge = WebviewBridge(service=LightControlService(controller=WizUdpController([])))
    cancelled = threading.Event()

    async def hanging_task() -> None:
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    try:
        with pytest.raises(TimeoutError):
            bridge._run_async(hanging_task(), timeout=0.05)
        assert cancelled.wait(timeout=2.0), "timed-out task was not cancelled"
    finally:
        bridge.shutdown()


def test_bridge_shutdown_handles_unstarted_and_already_closed_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = threading.Event()
    real_run_forever = asyncio.BaseEventLoop.run_forever

    def delayed_run_forever(self: asyncio.BaseEventLoop, *args: Any, **kwargs: Any) -> None:
        gate.wait(timeout=2.0)
        real_run_forever(self, *args, **kwargs)

    monkeypatch.setattr(asyncio.BaseEventLoop, "run_forever", delayed_run_forever)
    # Prevent constructor from blocking for full 5s _LOOP_START_TIMEOUT.
    monkeypatch.setattr("wiz_console.adapters.ui_webview.lifecycle._LOOP_START_TIMEOUT", 0.05)

    bridge = WebviewBridge(service=LightControlService(controller=WizUdpController([])))
    try:
        # Shut down BEFORE run_forever starts.
        gate.set()
        bridge.shutdown()
        assert bridge._thread.is_alive() is False

        # Second shutdown when loop is already closed must be an idempotent no-op.
        bridge.shutdown()

        # Subsequent _run_async must close the passed coroutine and raise RuntimeError.
        async def sample() -> int:
            return 1

        coro = sample()
        with pytest.raises(RuntimeError, match="not running"):
            bridge._run_async(coro)
    finally:
        gate.set()


# --- TrayController lost wakeup & start/stop race ---


def test_tray_controller_does_not_lose_refresh_requested_while_refreshing() -> None:
    refresh_entered = threading.Event()
    allow_refresh_exit = threading.Event()
    second_refresh = threading.Event()
    calls = 0

    class _SlowActions:
        def set_power(self, _is_on: bool) -> dict[str, Any]:
            return {"ok": True}

        def toggle_power(self) -> dict[str, Any]:
            return {"ok": True}

        def refresh_tray_states(self) -> dict[str, Any]:
            return {"ok": True}

        def set_brightness(self, _brightness: int) -> dict[str, Any]:
            return {"ok": True}

        def apply_custom_scene(self, _scene_id: str) -> dict[str, Any]:
            return {"ok": True}

        def cancel_sleep_timer(self) -> dict[str, Any]:
            return {"ok": True}

        def get_tray_snapshot(self) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls == 2:
                refresh_entered.set()
                allow_refresh_exit.wait(timeout=3.0)
            elif calls >= 3:
                second_refresh.set()
            return {
                "is_on": False,
                "brightness": 100,
                "presets": [],
                "language": "en",
                "theme": "architectural-stone",
            }

    view = _RecordingTrayView()
    tray = TrayController(
        _SlowActions(),
        show_window=lambda: None,
        hide_window=lambda: None,
        quit_app=lambda: None,
        is_window_visible=lambda: True,
        view_factory=lambda _d: view,
        poll_interval=3600.0,
    )
    try:
        tray.start()
        # Trigger the first worker refresh (calls == 2), then request another while blocked.
        tray.request_refresh()
        assert refresh_entered.wait(timeout=2.0)
        tray.request_refresh()
        allow_refresh_exit.set()
        assert second_refresh.wait(timeout=2.0), "refresh requested during refresh() was lost"
    finally:
        allow_refresh_exit.set()
        tray.stop()


def test_tray_stop_while_view_factory_runs_stops_created_view() -> None:
    in_factory = threading.Event()
    proceed_factory = threading.Event()
    created_views: list[_RecordingTrayView] = []

    def slow_factory(_dispatch: Any) -> _RecordingTrayView:
        in_factory.set()
        proceed_factory.wait(timeout=3.0)
        view = _RecordingTrayView()
        created_views.append(view)
        return view

    tray = TrayController(
        _FakeBridge(),  # type: ignore[arg-type]
        show_window=lambda: None,
        hide_window=lambda: None,
        quit_app=lambda: None,
        is_window_visible=lambda: True,
        view_factory=slow_factory,
    )
    starter = threading.Thread(target=tray.start, daemon=True)
    starter.start()
    try:
        assert in_factory.wait(timeout=2.0)
        tray.stop()
        proceed_factory.set()
        starter.join(timeout=2.0)
        assert len(created_views) == 1
        assert created_views[0].stop_calls == 1
        assert tray.view is None
        _wait_until(
            lambda: (
                not (
                    {ICON_THREAD_NAME, REFRESH_THREAD_NAME}
                    & {t.name for t in threading.enumerate()}
                )
            ),
            "tray threads were started after stop()",
        )
    finally:
        proceed_factory.set()
        tray.stop()


# --- Multi-monitor & high-DPI window geometry ---


def test_initial_window_geometry_prefers_primary_working_area_and_negative_origin() -> None:
    secondary_left = SimpleNamespace(
        x=-1920,
        y=0,
        width=1920,
        height=1080,
        frame=SimpleNamespace(X=-1920, Y=0, Width=1920, Height=1040),
    )
    primary = SimpleNamespace(
        x=0,
        y=0,
        width=1920,
        height=1080,
        frame=SimpleNamespace(X=0, Y=0, Width=1920, Height=1040),
    )
    width, height, x, y = _compute_initial_window_geometry(
        SimpleNamespace(screens=[secondary_left, primary])
    )
    assert (width, height) == (620, 760)
    assert (x, y) == ((1920 - 620) // 2, (1040 - 760) // 2)

    # Secondary-only negative monitor coordinates preserve monitor origin without clamping to 0.
    neg_w, neg_h, neg_x, neg_y = _compute_initial_window_geometry(
        SimpleNamespace(screens=[secondary_left])
    )
    assert (neg_w, neg_h) == (620, 760)
    assert neg_x == -1920 + (1920 - 620) // 2
    assert neg_y == (1040 - 760) // 2


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 ctypes fit test requires Windows")
def test_fit_native_window_height_handles_high_dpi_negative_work_area_and_controls_snapshot() -> (
    None
):
    hwnd_64 = 0x0000000240003333
    hmon_64 = 0x0000000390004444
    set_pos_calls: list[tuple[int, int, int, int, int, int, int]] = []

    class _FakeControls:
        def __init__(self) -> None:
            self.iterated = False

        def __iter__(self) -> Iterator[Any]:
            self.iterated = True
            return iter(
                [
                    SimpleNamespace(
                        GetType=lambda: SimpleNamespace(Name="MenuStrip"),
                        Visible=True,
                        Height=36,
                    )
                ]
            )

    controls = _FakeControls()

    class FakeUser32:
        def IsZoomed(self, _hwnd: int) -> int:  # noqa: N802
            return 0

        def IsIconic(self, _hwnd: int) -> int:  # noqa: N802
            return 0

        def IsWindowVisible(self, _hwnd: int) -> int:  # noqa: N802
            return 1

        def GetDpiForWindow(self, _hwnd: int) -> int:  # noqa: N802
            return 144  # 150% DPI scaling

        def GetWindowRect(self, _hwnd: int, rect_ptr: object) -> int:  # noqa: N802
            rect = ctypes.cast(rect_ptr, ctypes.POINTER(ctypes.wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = -1800, -100, -870, 950
            return 1

        def GetClientRect(self, _hwnd: int, rect_ptr: object) -> int:  # noqa: N802
            rect = ctypes.cast(rect_ptr, ctypes.POINTER(ctypes.wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 930, 990
            return 1

        def MonitorFromWindow(self, _hwnd: int, _flags: int) -> int:  # noqa: N802
            return hmon_64

        def GetMonitorInfoW(self, _monitor: int, info_ptr: object) -> int:  # noqa: N802
            raw_ints = ctypes.cast(info_ptr, ctypes.POINTER(ctypes.c_long * 10)).contents
            raw_ints[5] = -1920  # rcWork.left
            raw_ints[6] = 0  # rcWork.top (window starts above work_top at -100)
            raw_ints[7] = 0  # rcWork.right
            raw_ints[8] = 1560  # rcWork.bottom (1040 logical px at 1.5x)
            return 1

        def SetWindowPos(self, *args: int) -> int:  # noqa: N802
            set_pos_calls.append(args)  # type: ignore[arg-type]
            return 1

    fake_window = SimpleNamespace(
        native=SimpleNamespace(
            IsDisposed=False,
            Disposing=False,
            IsHandleCreated=True,
            InvokeRequired=False,
            Handle=SimpleNamespace(ToInt64=lambda: hwnd_64),
            Controls=controls,
        )
    )

    ok = _fit_native_window_height(fake_window, 660, platform="win32", user32=FakeUser32())
    assert ok is True
    assert controls.iterated is True
    # scale=1.5; outer_h=1050, client=990, menu=36 -> chrome_phys=96 -> chrome_logical=64
    # target_logical = 660 + 64 = 724 -> target_phys = 1086; top clamped from -100 to 0.
    assert set_pos_calls == [(hwnd_64, 0, -1800, 0, 930, 1086, 0x0004 | 0x0010)]

    # Disposing=True must abort cleanly.
    disposing_window = SimpleNamespace(
        native=SimpleNamespace(IsDisposed=False, Disposing=True, IsHandleCreated=True)
    )
    assert _fit_native_window_height(disposing_window, 660, platform="win32") is False


# --- main.py startup failure cleanup ---


def test_main_releases_guard_and_shuts_down_bridge_when_create_window_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    released: list[bool] = []
    shutdowns: list[bool] = []

    class _FakeGuard:
        def acquire(self) -> bool:
            return True

        def release(self) -> None:
            released.append(True)

    fake_bridge = SimpleNamespace(shutdown=lambda: shutdowns.append(True))

    class _FailingDesktopApp:
        def __init__(self, **_kwargs: Any) -> None:
            return None

        def create_window(self) -> None:
            raise RuntimeError("window creation boom")

    monkeypatch.setattr(main_module, "_configure_logging", lambda: None)
    monkeypatch.setattr(main_module, "resolve_ui_directory", lambda: tmp_path)
    monkeypatch.setattr(main_module, "resolve_icon_path", lambda: tmp_path / "app.ico")
    monkeypatch.setattr(main_module, "SingleInstanceGuard", _FakeGuard)
    monkeypatch.setattr(main_module, "_default_autostart", lambda: None)
    monkeypatch.setattr(
        main_module, "build_application", lambda autostart=None: (object(), fake_bridge)
    )
    monkeypatch.setattr(main_module, "apply_app_user_model_id", lambda: True)
    monkeypatch.setattr(main_module, "DesktopApplication", _FailingDesktopApp)

    with pytest.raises(RuntimeError, match="window creation boom"):
        main_module.main([])

    assert shutdowns == [True]
    assert released == [True]
