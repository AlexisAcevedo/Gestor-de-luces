"""Regression tests for async stream lifecycles, teardown, validation order, and logging."""

from __future__ import annotations

import asyncio
import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import pytest

from tests.waits import wait_until_async
from wiz_console import main as main_module
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application import ambilight_stream as ambilight_stream_module
from wiz_console.application import music_stream as music_stream_module
from wiz_console.application.ambilight_stream import AmbilightStreamManager
from wiz_console.application.music_stream import MusicSyncStreamManager
from wiz_console.application.rate_limiter import StreamRateLimiter
from wiz_console.application.service import LightControlService
from wiz_console.application.sleep_timer import SleepTimerManager
from wiz_console.domain.models import Bulb, LightState
from wiz_console.domain.value_objects import Color


class _StubController:
    """In-memory LightController test double that records close calls."""

    def __init__(self) -> None:
        self.closed = False
        self.bulbs = [Bulb(ip="192.168.1.10", mac="aabbccddeeff", is_online=True)]

    async def discover(self, wait_time: float = 2.5) -> list[Bulb]:
        return list(self.bulbs)

    async def probe_bulb(self, ip: str, timeout: float = 1.0) -> Bulb | None:
        return Bulb(ip=ip, is_online=True)

    async def get_state(self, ip: str, timeout: float = 1.0) -> LightState | None:
        return LightState()

    async def set_power(self, ip: str, is_on: bool, brightness: int | None = None) -> bool:
        return True

    async def set_brightness(self, ip: str, brightness: int) -> bool:
        return True

    async def set_color(self, ip: str, color: Color, brightness: int | None = None) -> bool:
        return True

    async def set_temperature(self, ip: str, kelvin: int, brightness: int | None = None) -> bool:
        return True

    async def set_scene(
        self,
        ip: str,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
    ) -> bool:
        return True

    async def stream_pilot(self, ip: str, color: Color, brightness: int) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _TrackingScreenSampler:
    def __init__(self, color: Color | None = None, brightness: int = 80) -> None:
        self.color = color or Color(10, 20, 30)
        self.brightness = brightness
        self.closed = False

    def list_monitors(self) -> list[dict[str, Any]]:
        return [{"index": 1, "label": "Display 1", "width": 1920, "height": 1080}]

    def sample_frame(self, monitor_index: int = 1, mode: str = "vibrant") -> tuple[Color, int]:
        return self.color, self.brightness

    def sample_average_color(self, monitor_index: int = 1, mode: str = "average") -> Color:
        return self.color

    def close(self) -> None:
        self.closed = True


class _TrackingAudioSampler:
    def __init__(
        self,
        color: Color | None = None,
        brightness: int = 75,
        *,
        fail_on_close: bool = False,
    ) -> None:
        self.color = color or Color(40, 80, 120)
        self.brightness = brightness
        self.fail_on_close = fail_on_close
        self.closed = False

    def list_audio_devices(self) -> list[dict[str, Any]]:
        return [
            {
                "index": 1,
                "name": "Loopback",
                "label": "Default",
                "sample_rate": 48000,
                "channels": 2,
                "is_default": True,
            }
        ]

    def sample_frame(
        self,
        device_index: int | None = None,
        palette_mode: str = "spectrum",
        sensitivity: float = 1.0,
    ) -> dict[str, Any]:
        return {
            "rms": 0.5,
            "bass": 0.4,
            "mid": 0.3,
            "treble": 0.2,
            "brightness": self.brightness,
            "color": self.color,
        }

    def sample_audio_metrics(self) -> tuple[float, Color]:
        return 0.5, self.color

    def close(self) -> None:
        self.closed = True
        if self.fail_on_close:
            raise RuntimeError("audio close failed")


async def test_sleep_timer_restart_race_preserves_second_timer() -> None:
    """Cancelling an old SleepTimer task must not wipe out a newly started timer."""
    mgr = SleepTimerManager()
    t1_expired: list[list[str]] = []
    t2_expired: list[list[str]] = []

    async def _noop_step(_b: int, _ips: list[str]) -> None:
        return None

    async def _expire_1(ips: list[str]) -> None:
        t1_expired.append(ips)

    async def _expire_2(ips: list[str]) -> None:
        t2_expired.append(ips)

    mgr.start(
        duration_seconds=5.0,
        target_ips=["192.168.1.10"],
        initial_brightness=80,
        on_step_brightness=_noop_step,
        on_expire_power_off=_expire_1,
    )
    # Yield once so T1 actually enters _run_countdown's try/finally before being cancelled.
    await asyncio.sleep(0)

    status_2 = mgr.start(
        duration_seconds=0.06,
        target_ips=["192.168.1.20"],
        initial_brightness=60,
        on_step_brightness=_noop_step,
        on_expire_power_off=_expire_2,
    )
    assert status_2["active"] is True

    # Let the cancelled T1 task execute its CancelledError / finally block.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    mid_status = mgr.get_status()
    assert mid_status["active"] is True
    assert mid_status["target_ips"] == ["192.168.1.20"]

    await wait_until_async(lambda: len(t2_expired) == 1, "second sleep timer never expired")
    assert t2_expired == [["192.168.1.20"]]
    assert t1_expired == []
    assert mgr.get_status()["active"] is False


async def test_ambilight_restart_race_discards_stale_frame() -> None:
    """Restarting Ambilight while an old thread is sampling must not drop or corrupt T2."""

    class _BlockingSampler(_TrackingScreenSampler):
        def __init__(self) -> None:
            super().__init__(color=Color(255, 0, 0), brightness=90)
            self.entered = threading.Event()
            self.release = threading.Event()
            self.finished = threading.Event()

        def sample_frame(self, monitor_index: int = 1, mode: str = "vibrant") -> tuple[Color, int]:
            self.entered.set()
            self.release.wait(timeout=5.0)
            self.finished.set()
            return self.color, self.brightness

    s1 = _BlockingSampler()
    s2 = _TrackingScreenSampler(color=Color(10, 20, 30), brightness=75)
    mgr = AmbilightStreamManager(sampler=s1, interval_seconds=0.01)

    frames_1: list[tuple[Color, int, list[str]]] = []
    frames_2: list[tuple[Color, int, list[str]]] = []

    async def _on_frame_1(color: Color, bri: int, ips: list[str]) -> bool:
        frames_1.append((color, bri, ips))
        return True

    async def _on_frame_2(color: Color, bri: int, ips: list[str]) -> bool:
        frames_2.append((color, bri, ips))
        return True

    mgr.start(sampler=s1, target_ips=["192.168.1.10"], on_frame=_on_frame_1)
    await wait_until_async(s1.entered.is_set, "first ambilight sampler never entered thread")

    mgr.start(sampler=s2, target_ips=["192.168.1.20"], on_frame=_on_frame_2)
    s1.release.set()
    await wait_until_async(s1.finished.is_set, "first ambilight sampler never exited thread")

    await wait_until_async(
        lambda: len(frames_2) >= 2,
        "second ambilight stream never published frames",
    )
    assert mgr.get_status()["active"] is True
    assert frames_1 == []
    assert all(color == Color(10, 20, 30) for color, _bri, _ips in frames_2)
    mgr.stop()


async def test_music_sync_restart_race_discards_stale_frame() -> None:
    """Restarting Music Sync while an old thread is sampling must not drop or corrupt T2."""

    class _BlockingAudioSampler(_TrackingAudioSampler):
        def __init__(self) -> None:
            super().__init__(color=Color(255, 0, 0), brightness=95)
            self.entered = threading.Event()
            self.release = threading.Event()
            self.finished = threading.Event()

        def sample_frame(
            self,
            device_index: int | None = None,
            palette_mode: str = "spectrum",
            sensitivity: float = 1.0,
        ) -> dict[str, Any]:
            self.entered.set()
            self.release.wait(timeout=5.0)
            self.finished.set()
            return super().sample_frame(device_index, palette_mode, sensitivity)

    s1 = _BlockingAudioSampler()
    s2 = _TrackingAudioSampler(color=Color(15, 25, 35), brightness=65)
    mgr = MusicSyncStreamManager(sampler=s1, interval_seconds=0.01)

    frames_1: list[tuple[Color, int, list[str]]] = []
    frames_2: list[tuple[Color, int, list[str]]] = []

    async def _on_frame_1(color: Color, bri: int, ips: list[str]) -> bool:
        frames_1.append((color, bri, ips))
        return True

    async def _on_frame_2(color: Color, bri: int, ips: list[str]) -> bool:
        frames_2.append((color, bri, ips))
        return True

    mgr.start(sampler=s1, target_ips=["192.168.1.10"], on_frame=_on_frame_1)
    await wait_until_async(s1.entered.is_set, "first music sampler never entered thread")

    mgr.start(sampler=s2, target_ips=["192.168.1.20"], on_frame=_on_frame_2)
    s1.release.set()
    await wait_until_async(s1.finished.is_set, "first music sampler never exited thread")

    await wait_until_async(
        lambda: len(frames_2) >= 2,
        "second music sync stream never published frames",
    )
    assert mgr.get_status()["active"] is True
    assert frames_1 == []
    assert all(color == Color(15, 25, 35) for color, _bri, _ips in frames_2)
    mgr.stop()


def test_stop_music_sync_close_sampler_only_closes_audio_and_clears_ref() -> None:
    """close_sampler=True closes only audio_sampler and clears it for lazy recreation."""
    controller = _StubController()
    screen_sampler = _TrackingScreenSampler()
    created_audio = [_TrackingAudioSampler(), _TrackingAudioSampler()]
    idx = {"n": 0}

    def _audio_factory() -> _TrackingAudioSampler:
        sampler = created_audio[idx["n"]]
        idx["n"] += 1
        return sampler

    service = LightControlService(
        controller=controller,
        screen_sampler=screen_sampler,
        audio_sampler_factory=_audio_factory,
    )
    service.list_audio_devices()
    service.list_monitors()

    service.stop_music_sync(close_sampler=True)

    assert created_audio[0].closed is True
    assert screen_sampler.closed is False
    assert controller.closed is False

    # Next audio operation creates a fresh sampler via factory.
    service.list_audio_devices()
    assert idx["n"] == 2
    assert created_audio[1].closed is False


def test_close_all_resources_handles_exceptions_and_closes_everything() -> None:
    """close_all_resources() closes audio, screen, and controller even if one raises."""
    controller = _StubController()
    screen_sampler = _TrackingScreenSampler()
    audio_sampler = _TrackingAudioSampler(fail_on_close=True)

    service = LightControlService(
        controller=controller,
        screen_sampler=screen_sampler,
        audio_sampler=audio_sampler,
    )
    service.close_all_resources()

    assert audio_sampler.closed is True
    assert screen_sampler.closed is True
    assert controller.closed is True


async def test_close_audio_sampler_waits_for_inflight_sample() -> None:
    """Closing the audio sampler waits for any in-flight sample_frame thread to exit."""

    class _SlowAudioSampler(_TrackingAudioSampler):
        def __init__(self) -> None:
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()
            self.in_sample = False
            self.overlapped = False

        def sample_frame(
            self,
            device_index: int | None = None,
            palette_mode: str = "spectrum",
            sensitivity: float = 1.0,
        ) -> dict[str, Any]:
            self.in_sample = True
            self.entered.set()
            try:
                self.release.wait(timeout=5.0)
                return super().sample_frame(device_index, palette_mode, sensitivity)
            finally:
                self.in_sample = False

        def close(self) -> None:
            if self.in_sample:
                self.overlapped = True
            super().close()

    controller = _StubController()
    sampler = _SlowAudioSampler()
    service = LightControlService(controller=controller, audio_sampler=sampler)
    await service.discover_bulbs()

    service.start_music_sync(palette_mode="spectrum")
    await wait_until_async(sampler.entered.is_set, "music sampler never entered sample_frame")

    closer = threading.Thread(
        target=lambda: service.stop_music_sync(close_sampler=True),
        daemon=True,
    )
    closer.start()

    # stop_music_sync calls music_sync.stop() immediately, then blocks on sampler lock.
    await wait_until_async(
        lambda: service.get_music_sync_status()["active"] is False,
        "music sync never marked inactive before waiting on sampler lock",
    )
    assert sampler.closed is False

    sampler.release.set()
    await wait_until_async(lambda: sampler.closed, "audio sampler was never closed")
    closer.join(timeout=5.0)
    assert closer.is_alive() is False
    assert sampler.overlapped is False


def test_webview_bridge_shutdown_closes_all_resources() -> None:
    """WebviewBridge.shutdown() closes audio, screen, and UDP controller."""
    controller = _StubController()
    screen_sampler = _TrackingScreenSampler()
    audio_sampler = _TrackingAudioSampler()
    service = LightControlService(
        controller=controller,
        screen_sampler=screen_sampler,
        audio_sampler=audio_sampler,
    )
    bridge = WebviewBridge(service=service)
    bridge.shutdown()

    assert audio_sampler.closed is True
    assert screen_sampler.closed is True
    assert controller.closed is True


@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf"), True, False])
async def test_nan_inf_bool_rejected_across_managers_and_services(bad_val: Any) -> None:
    """NaN, Inf, and bool inputs raise ValueError across stream managers and services."""
    controller = _StubController()
    service = LightControlService(
        controller=controller,
        screen_sampler=_TrackingScreenSampler(),
        audio_sampler=_TrackingAudioSampler(),
    )

    with pytest.raises(ValueError):
        AmbilightStreamManager(interval_seconds=bad_val)
    with pytest.raises(ValueError):
        MusicSyncStreamManager(interval_seconds=bad_val)

    timer_mgr = SleepTimerManager()

    async def _noop(*_args: Any) -> None:
        return None

    with pytest.raises(ValueError):
        timer_mgr.start(
            duration_seconds=bad_val,
            target_ips=[],
            initial_brightness=50,
            on_step_brightness=_noop,
            on_expire_power_off=_noop,
        )
    with pytest.raises(ValueError):
        service.start_sleep_timer(minutes=bad_val)
    with pytest.raises(ValueError):
        service.start_ambilight(smoothing_alpha=bad_val)
    with pytest.raises(ValueError):
        service.start_ambilight(brightness=bad_val)
    with pytest.raises(ValueError):
        service.start_music_sync(sensitivity=bad_val)
    with pytest.raises(ValueError):
        service.start_music_sync(smoothing_alpha=bad_val)
    with pytest.raises(ValueError):
        service.start_music_sync(brightness=bad_val)


async def test_validation_errors_cause_no_side_effects() -> None:
    """Invalid calls must raise before stopping active streams or mutating rate_limiter."""
    controller = _StubController()
    limiter = StreamRateLimiter(max_hz=10.0, alpha=0.38)
    service = LightControlService(
        controller=controller,
        rate_limiter=limiter,
        screen_sampler=_TrackingScreenSampler(),
        audio_sampler=_TrackingAudioSampler(),
    )
    await service.discover_bulbs()

    # Start Ambilight and seed rate_limiter for a bulb.
    service.start_ambilight(brightness=85, smoothing_alpha=0.38)
    assert service.get_ambilight_status()["active"] is True
    assert limiter.prepare_frame("192.168.1.10", Color(100, 100, 100), 85) is not None

    with pytest.raises(ValueError):
        await service.set_power(False, ips=["8.8.8.8"])
    with pytest.raises(ValueError):
        await service.set_power(False, brightness=5)
    with pytest.raises(ValueError):
        await service.set_color(10, 20, 30, ips=["8.8.8.8"])
    with pytest.raises(ValueError):
        await service.set_temperature(3000, ips=["8.8.8.8"])
    with pytest.raises(ValueError):
        await service.set_builtin_scene(1, ips=["8.8.8.8"])
    with pytest.raises(ValueError):
        await service.set_brightness(50, ips=["8.8.8.8"])
    with pytest.raises(ValueError):
        await service.set_brightness(True)  # type: ignore[arg-type]

    assert service.get_ambilight_status()["active"] is True
    assert service.get_ambilight_status()["fixed_brightness"] == 85

    # Invalid start_music_sync must NOT stop Ambilight or reset rate_limiter.
    with pytest.raises(ValueError):
        service.start_music_sync(palette_mode="invalid")
    with pytest.raises(ValueError):
        service.start_music_sync(sensitivity=99.0)
    with pytest.raises(ValueError):
        service.start_music_sync(ips=["8.8.8.8"])
    with pytest.raises(ValueError):
        service.start_music_sync(smoothing_alpha=float("nan"))

    assert service.get_ambilight_status()["active"] is True
    assert limiter.alpha == pytest.approx(0.38)
    # Still rate-limited from the seeded frame (not reset!).
    assert limiter.prepare_frame("192.168.1.10", Color(200, 200, 200), 90) is None

    # Now switch to Music Sync and verify invalid start_ambilight does not disturb it.
    service.start_music_sync(palette_mode="spectrum", smoothing_alpha=0.50)
    assert service.get_music_sync_status()["active"] is True
    assert limiter.prepare_frame("192.168.1.10", Color(100, 100, 100), 85) is not None

    with pytest.raises(ValueError):
        service.start_ambilight(color_mode="invalid")
    with pytest.raises(ValueError):
        service.start_ambilight(ips=["8.8.8.8"])
    with pytest.raises(ValueError):
        service.start_ambilight(smoothing_alpha=float("nan"))

    assert service.get_music_sync_status()["active"] is True
    assert limiter.alpha == pytest.approx(0.50)
    assert limiter.prepare_frame("192.168.1.10", Color(200, 200, 200), 90) is None

    service.close_all_resources()


async def test_ambilight_stream_error_backoff_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambilight applies bounded exponential backoff on repeated errors and resets on success."""
    recorded_delays: list[float] = []
    real_sleep = asyncio.sleep
    recovered = asyncio.Event()

    class _FlakySampler(_TrackingScreenSampler):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def sample_frame(self, monitor_index: int = 1, mode: str = "vibrant") -> tuple[Color, int]:
            self.calls += 1
            if self.calls <= 3:
                raise RuntimeError(f"boom {self.calls}")
            return super().sample_frame(monitor_index, mode)

    class _AsyncioProxy:
        def __getattr__(self, name: str) -> Any:
            return getattr(asyncio, name)

        async def sleep(self, delay: float) -> None:
            recorded_delays.append(round(delay, 4))
            await real_sleep(0)

    monkeypatch.setattr(ambilight_stream_module, "asyncio", _AsyncioProxy())

    mgr = AmbilightStreamManager(
        sampler=_FlakySampler(),
        interval_seconds=0.1,
        max_error_backoff=0.5,
    )

    successes = 0

    async def _on_frame(_c: Color, _b: int, _ips: list[str]) -> bool:
        nonlocal successes
        successes += 1
        if successes >= 2:
            recovered.set()
            mgr.stop()
        return True

    mgr.start(sampler=mgr._sampler, target_ips=["192.168.1.10"], on_frame=_on_frame)
    await asyncio.wait_for(recovered.wait(), timeout=5.0)
    assert recorded_delays[:4] == [0.2, 0.4, 0.5, 0.1]


async def test_music_stream_error_backoff_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Music Sync applies bounded exponential backoff on repeated errors and resets on success."""
    recorded_delays: list[float] = []
    real_sleep = asyncio.sleep
    recovered = asyncio.Event()

    class _FlakyAudioSampler(_TrackingAudioSampler):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def sample_frame(
            self,
            device_index: int | None = None,
            palette_mode: str = "spectrum",
            sensitivity: float = 1.0,
        ) -> dict[str, Any]:
            self.calls += 1
            if self.calls <= 3:
                raise RuntimeError(f"boom {self.calls}")
            return super().sample_frame(device_index, palette_mode, sensitivity)

    class _AsyncioProxy:
        def __getattr__(self, name: str) -> Any:
            return getattr(asyncio, name)

        async def sleep(self, delay: float) -> None:
            recorded_delays.append(round(delay, 4))
            await real_sleep(0)

    monkeypatch.setattr(music_stream_module, "asyncio", _AsyncioProxy())

    mgr = MusicSyncStreamManager(
        sampler=_FlakyAudioSampler(),
        interval_seconds=0.1,
        max_error_backoff=0.5,
    )

    successes = 0

    async def _on_frame(_c: Color, _b: int, _ips: list[str]) -> bool:
        nonlocal successes
        successes += 1
        if successes >= 2:
            recovered.set()
            mgr.stop()
        return True

    mgr.start(sampler=mgr._sampler, target_ips=["192.168.1.10"], on_frame=_on_frame)
    await asyncio.wait_for(recovered.wait(), timeout=5.0)
    assert recorded_delays[:4] == [0.2, 0.4, 0.5, 0.1]


def test_configure_logging_uses_rotating_file_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_configure_logging() configures a bounded RotatingFileHandler in data_dir."""
    monkeypatch.setattr(main_module, "resolve_default_data_dir", lambda: tmp_path)
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    root.handlers.clear()
    added_handlers: list[logging.Handler] = []
    try:
        main_module._configure_logging()
        added_handlers = list(root.handlers)
        rotating = [h for h in added_handlers if isinstance(h, RotatingFileHandler)]
        assert len(rotating) == 1
        handler = rotating[0]
        assert Path(handler.baseFilename) == tmp_path / "wiz_console.log"
        assert handler.maxBytes == main_module.LOG_MAX_BYTES
        assert handler.backupCount == main_module.LOG_BACKUP_COUNT
    finally:
        for handler in added_handlers:
            root.removeHandler(handler)
            handler.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_real_controller_close_is_idempotent() -> None:
    """Sanity check that WizUdpController.close() can be called from close_all_resources."""
    service = LightControlService(controller=WizUdpController(probe_candidates=[]))
    service.close_all_resources()
    service.close_all_resources()
