"""Stability, concurrency, and resource-safety tests for WASAPI and MSS adapters."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

import mss.exception
import numpy as np
import pytest

from wiz_console.adapters.ambilight import MssScreenSampler, extract_color_and_brightness_from_bgra
from wiz_console.adapters.audio import WasapiLoopbackSampler, analyze_pcm_audio_frame
from wiz_console.adapters.audio import wasapi_capture as wasapi_capture_module
from wiz_console.adapters.audio.wasapi_session import WasapiLoopbackStreamSession
from wiz_console.domain.value_objects import Color


class _FakeStream:
    def __init__(self, callback: Any, *, fail_on_start: bool = False) -> None:
        self.callback = callback
        self.fail_on_start = fail_on_start
        self.active = True
        self.stopped = False
        self.closed = False

    def start_stream(self) -> None:
        if self.fail_on_start:
            raise OSError("stream start failed")
        self.active = True

    def stop_stream(self) -> None:
        self.stopped = True
        self.active = False

    def close(self) -> None:
        self.closed = True
        self.active = False

    def is_active(self) -> bool:
        return self.active

    def is_stopped(self) -> bool:
        return not self.active


class _FakePyAudio:
    def __init__(
        self,
        *,
        fail_at: str | None = None,
        default_index: int = 7,
        on_open: Any = None,
    ) -> None:
        self.fail_at = fail_at
        self.default_index = default_index
        self.on_open = on_open
        self.terminated = False
        self.opened_indices: list[int] = []
        self.streams: list[_FakeStream] = []
        self.devices: dict[int, dict[str, Any]] = {
            4: {
                "index": 4,
                "name": "Headphones (USB DAC) [Loopback]",
                "defaultSampleRate": 48000.0,
                "maxInputChannels": 2,
            },
            7: {
                "index": 7,
                "name": "Speakers (Realtek Audio) [Loopback]",
                "defaultSampleRate": 48000.0,
                "maxInputChannels": 2,
            },
            9: {
                "index": 9,
                "name": "HDMI Display [Loopback]",
                "defaultSampleRate": 48000.0,
                "maxInputChannels": 2,
            },
        }

    def get_default_wasapi_loopback(self) -> dict[str, Any]:
        if self.fail_at == "get_default":
            raise OSError("no default loopback endpoint")
        return dict(self.devices[self.default_index])

    def get_loopback_device_info_generator(self) -> Any:
        for dev in self.devices.values():
            yield dict(dev)

    def get_device_info_by_index(self, idx: int) -> dict[str, Any]:
        if idx not in self.devices:
            raise OSError(f"Unknown device {idx}")
        return dict(self.devices[idx])

    def open(self, **kwargs: Any) -> _FakeStream:
        if self.fail_at == "open":
            raise OSError("device busy")
        if self.on_open is not None:
            self.on_open()
        self.opened_indices.append(int(kwargs["input_device_index"]))
        stream = _FakeStream(
            callback=kwargs.get("stream_callback"),
            fail_on_start=(self.fail_at == "start_stream"),
        )
        self.streams.append(stream)
        return stream

    def terminate(self) -> None:
        self.terminated = True


@pytest.mark.parametrize("fail_at", ["get_default", "open", "start_stream"])
def test_ensure_stream_terminates_pyaudio_and_closes_stream_on_setup_errors(
    fail_at: str,
) -> None:
    """Partial setup failures in ensure_stream must never leak PyAudio or stream handles."""
    created: list[_FakePyAudio] = []

    def _factory() -> _FakePyAudio:
        pa = _FakePyAudio(fail_at=fail_at)
        created.append(pa)
        return pa

    session = WasapiLoopbackStreamSession(pyaudio_factory=_factory)
    assert session.ensure_stream(None) is False
    assert len(created) == 1
    assert created[0].terminated is True
    if fail_at == "start_stream":
        assert len(created[0].streams) == 1
        assert created[0].streams[0].stopped is True
        assert created[0].streams[0].closed is True


def test_session_open_close_race_leaves_no_zombie_stream_and_no_deadlock() -> None:
    """Concurrent ensure_stream() and close() serialize cleanly with no leaked stream."""
    entered_open = threading.Event()
    release_open = threading.Event()
    created: list[_FakePyAudio] = []

    def _on_open() -> None:
        entered_open.set()
        release_open.wait(timeout=5.0)

    def _factory() -> _FakePyAudio:
        pa = _FakePyAudio(on_open=_on_open)
        created.append(pa)
        return pa

    session = WasapiLoopbackStreamSession(pyaudio_factory=_factory)
    opener = threading.Thread(target=lambda: session.ensure_stream(None), daemon=True)
    opener.start()
    assert entered_open.wait(timeout=5.0)

    closer = threading.Thread(target=session.close, daemon=True)
    closer.start()
    release_open.set()

    opener.join(timeout=5.0)
    closer.join(timeout=5.0)
    assert not opener.is_alive()
    assert not closer.is_alive()
    assert len(created) == 1
    assert created[0].terminated is True
    assert created[0].streams[0].closed is True
    assert session._stream is None
    assert session._pa is None

    # Callback + read + close never deadlock.
    session._pyaudio_factory = lambda: _FakePyAudio()
    assert session.ensure_stream(None) is True
    active_pa = session._pa
    assert active_pa is not None
    active_pa.streams[0].callback(b"\x00" * 16, 2, {}, 0)
    pcm, ts, rate, ch = session.read()
    assert len(pcm) == 16 and ts > 0 and rate == 48000 and ch == 2
    session.close()


def test_session_recovers_from_hot_unplug_and_default_device_switch() -> None:
    """ensure_stream() reopens on stopped stream (hot-unplug) or default-device change."""
    state = {"default_idx": 7}
    instances: list[_FakePyAudio] = []

    def _factory() -> _FakePyAudio:
        pa = _FakePyAudio(default_index=state["default_idx"])
        instances.append(pa)
        return pa

    session = WasapiLoopbackStreamSession(
        pyaudio_factory=_factory,
        default_device_check_interval=0.0,
    )
    assert session.ensure_stream(None) is True
    assert len(instances) == 1
    assert instances[0].opened_indices == [7]

    # 1. Hot-unplug: active stream becomes inactive -> session closes and reopens.
    instances[0].streams[0].active = False
    assert session.ensure_stream(None) is True
    assert instances[0].streams[0].closed is True
    assert instances[0].terminated is True
    assert len(instances) == 2
    assert instances[1].opened_indices == [7]

    # 2. Default Windows output switches from 7 -> 9 -> session switches automatically.
    state["default_idx"] = 9
    instances[1].default_index = 9
    assert session.ensure_stream(None) is True
    assert instances[1].streams[0].closed is True
    assert instances[1].terminated is True
    assert len(instances) == 3
    assert instances[2].opened_indices == [9]

    # 3. Explicit device index stays pinned even if Windows default changes again.
    assert session.ensure_stream(4) is True
    assert len(instances) == 4
    assert instances[3].opened_indices == [4]
    state["default_idx"] = 7
    instances[3].default_index = 7
    assert session.ensure_stream(4) is True
    assert len(instances) == 4
    session.close()


def test_analyze_pcm_audio_frame_handles_unaligned_bytes_and_nan_sensitivity() -> None:
    """Unaligned PCM byte lengths and non-finite sensitivity never raise ValueError."""
    for short_len in (1, 2, 3):
        metrics = analyze_pcm_audio_frame(b"\x01" * short_len)
        assert metrics["rms"] == 0.0

    sample_rate = 48000
    t = np.arange(4096, dtype=np.float32) / float(sample_rate)
    mono = (0.65 * np.sin(2.0 * np.pi * 80.0 * t)).astype(np.float32)
    stereo_bytes = np.column_stack((mono, mono)).reshape(-1).tobytes()

    unaligned = stereo_bytes + b"\xaa\xbb\xcc"
    metrics = analyze_pcm_audio_frame(unaligned, sample_rate=sample_rate, channels=2)
    assert metrics["bass"] > 0.7

    for bad_sens in (float("nan"), float("inf"), True):
        res = analyze_pcm_audio_frame(
            stereo_bytes,
            sample_rate=sample_rate,
            channels=2,
            sensitivity=bad_sens,  # type: ignore[arg-type]
        )
        assert math.isfinite(res["rms"])
        assert 10 <= res["brightness"] <= 100


def test_fft_plan_is_cached_readonly_and_matches_exact_band_masks() -> None:
    """_fft_plan caches immutable Hann window and contiguous frequency band slices."""
    wasapi_capture_module._fft_plan.cache_clear()
    plan_1 = wasapi_capture_module._fft_plan(4096, 48000)
    plan_2 = wasapi_capture_module._fft_plan(4096, 48000)

    assert plan_1[0] is plan_2[0]
    assert plan_1[0].flags.writeable is False
    assert wasapi_capture_module._fft_plan.cache_info().hits >= 1

    freqs = np.fft.rfftfreq(4096, d=1.0 / 48000.0)
    _, _, bass_slice, mid_slice, treble_slice = plan_1
    assert np.array_equal(freqs[bass_slice], freqs[(freqs >= 20.0) & (freqs < 250.0)])
    assert np.array_equal(freqs[mid_slice], freqs[(freqs >= 250.0) & (freqs < 2000.0)])
    assert np.array_equal(freqs[treble_slice], freqs[(freqs >= 2000.0) & (freqs <= 12000.0)])


def test_list_caches_prevent_caller_mutation_and_close_clears_audio_cache() -> None:
    """Callers mutating returned device/monitor lists must not corrupt sampler caches."""
    pa_calls = {"count": 0}

    def _pa_factory() -> _FakePyAudio:
        pa_calls["count"] += 1
        return _FakePyAudio()

    audio = WasapiLoopbackSampler(pyaudio_factory=_pa_factory)
    devs_1 = audio.list_audio_devices()
    devs_1[0]["label"] = "MUTATED"
    devs_1.append({"index": 999, "label": "FAKE"})

    devs_2 = audio.list_audio_devices()
    assert len(devs_2) == 3
    assert devs_2[0]["label"] != "MUTATED"

    audio.close()
    assert pa_calls["count"] == 1
    audio.list_audio_devices()
    assert pa_calls["count"] == 2

    @dataclass
    class _Shot:
        bgra: bytes
        width: int
        height: int

    class _Ctx:
        monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]

        def __enter__(self) -> _Ctx:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def grab(self, _mon: dict[str, int]) -> _Shot:
            return _Shot(bgra=bytes([10, 20, 30, 255]) * 16, width=4, height=4)

    screen = MssScreenSampler(sct_factory=_Ctx)
    mons_1 = screen.list_monitors()
    mons_1[0]["width"] = 0
    mons_1.append({"index": 99, "label": "FAKE", "width": 1, "height": 1})

    mons_2 = screen.list_monitors()
    assert len(mons_2) == 1
    assert mons_2[0]["width"] == 1920


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: mss.exception.ScreenShotError("GDI failed"),
        lambda: OSError("desktop locked"),
    ],
)
def test_mss_screen_sampler_catches_screenshot_error_and_oserror_at_boundary(
    exc_factory: Any,
) -> None:
    """ScreenShotError/OSError during grab degrades to standby frame and invalidates cache."""
    enum_calls = {"count": 0}

    class _FailingGrabCtx:
        def __init__(self) -> None:
            enum_calls["count"] += 1
            self.monitors = [
                {"left": 0, "top": 0, "width": 1920, "height": 1080},
                {"left": 0, "top": 0, "width": 1920, "height": 1080},
            ]

        def __enter__(self) -> _FailingGrabCtx:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def grab(self, _mon: dict[str, int]) -> Any:
            raise exc_factory()

    sampler = MssScreenSampler(sct_factory=_FailingGrabCtx)
    assert len(sampler.list_monitors()) == 1
    assert enum_calls["count"] == 1

    assert sampler.sample_frame(monitor_index=1, mode="vibrant") == (Color(0, 0, 0), 10)
    assert sampler.sample_average_color(monitor_index=1, mode="average") == Color(0, 0, 0)

    # Cache must have been invalidated on capture error so list_monitors() re-enumerates.
    sampler.list_monitors()
    assert enum_calls["count"] == 4  # 1 init + 2 sample_frame + 1 list_monitors


def test_bgra_extraction_handles_short_buffer_and_matches_bt709_luminance() -> None:
    """Truncated buffers degrade safely and average/vibrant produce identical BT.709 brightness."""
    assert extract_color_and_brightness_from_bgra(b"\xff" * 10, width=16, height=16) == (
        Color(0, 0, 0),
        10,
    )

    black = bytes([0, 0, 0, 255]) * (8 * 8)
    white = bytes([255, 255, 255, 255]) * (8 * 8)
    assert extract_color_and_brightness_from_bgra(black, 8, 8, mode="average", stride=1) == (
        Color(0, 0, 0),
        10,
    )
    assert extract_color_and_brightness_from_bgra(white, 8, 8, mode="vibrant", stride=1) == (
        Color(255, 255, 255),
        100,
    )

    frame = np.zeros((16, 16, 4), dtype=np.uint8)
    frame[:, :, 0] = 40
    frame[:, :, 1] = 100
    frame[:, :, 2] = 200
    frame[:, :, 3] = 255
    avg_color, avg_bri = extract_color_and_brightness_from_bgra(
        frame.tobytes(), 16, 16, mode="average", stride=2
    )
    vib_color, vib_bri = extract_color_and_brightness_from_bgra(
        frame.tobytes(), 16, 16, mode="vibrant", stride=2
    )
    assert avg_color == Color(200, 100, 40)
    assert vib_color == Color(219, 97, 24)
    expected_lum = (0.2126 * 200 + 0.7152 * 100 + 0.0722 * 40) / 255.0
    assert avg_bri == vib_bri == round(10.0 + expected_lum * 90.0)
