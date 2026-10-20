"""Pruebas unitarias y de integracion para la Reaccion a la Musica y WASAPI Loopback (Fase 7).

Cubre:
1. Procesamiento digital de senales (DSP) determinista en `analyze_pcm_audio_frame`:
   - Silencio digital (`np.zeros`) produce `rms == 0.0` y brillo de reposo (`10-15%`).
   - Onda senoidal sintetica de `80 Hz` concentra la energia en `bass` (> `mid` y `treble`)
     y excita el canal rojo/calido en la paleta `"spectrum"`.
   - Onda senoidal sintetica de `1000 Hz` concentra la energia en `mid` (> `bass` y `treble`)
     y excita el canal verde en la paleta `"spectrum"`.
   - Onda senoidal sintetica de `6000 Hz` concentra la energia en `treble` (> `bass` y `mid`)
     y excita el canal azul en la paleta `"spectrum"`.
2. Comportamiento de `WasapiLoopbackSampler` ante el corte de callbacks de Windows WASAPI
   en silencio (deteccion instantanea por timeout sin bloquear hilos) y listado de dispositivos.
3. Flujo continuo asincrono (`MusicSyncStreamManager` + `LightControlService` + `WizUdpController`)
   contra `FakeWizBulbServer` sobre sockets UDP reales y exclusion mutua con Ambilight.
4. Ciclo de vida completo expuesto por `WebviewBridge` (`start_music_sync`, `get_music_sync_status`,
   `stop_music_sync`).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np

from gestor_luces.adapters.ambilight import MssScreenSampler
from gestor_luces.adapters.audio import WasapiLoopbackSampler, analyze_pcm_audio_frame
from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.ambilight_stream import AmbilightStreamManager
from gestor_luces.application.music_stream import MusicSyncStreamManager
from gestor_luces.application.rate_limiter import StreamRateLimiter
from gestor_luces.application.service import LightControlService
from gestor_luces.domain.value_objects import Color
from gestor_luces.ports.interfaces import AudioSampler
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer


def _make_stereo_sine_wave(
    freq_hz: float,
    sample_rate: int = 48000,
    num_frames: int = 4096,
    amplitude: float = 0.65,
) -> np.ndarray:
    """Genera una onda senoidal estereo entrelazada (`float32`) de frecuencia exacta."""
    t = np.arange(num_frames, dtype=np.float32) / float(sample_rate)
    mono = (amplitude * np.sin(2.0 * np.pi * float(freq_hz) * t)).astype(np.float32)
    stereo = np.column_stack((mono, mono)).reshape(-1)
    return stereo


class _FakePortAudioStream:
    """Simula un stream no bloqueante de PyAudioWPatch con callback de captura."""

    def __init__(self, callback: Any) -> None:
        self.callback = callback
        self.started = False
        self.closed = False

    def start_stream(self) -> None:
        self.started = True

    def stop_stream(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class _FakePyAudioWPatch:
    """Doble de prueba para `pyaudiowpatch.PyAudio` sin requerir hardware de audio fisico."""

    def __init__(self) -> None:
        self.last_stream: _FakePortAudioStream | None = None
        self.terminated = False
        self._devices = [
            {
                "index": 4,
                "name": "Headphones (USB DAC) [Loopback]",
                "defaultSampleRate": 48000.0,
                "maxInputChannels": 2,
            },
            {
                "index": 7,
                "name": "Speakers (Realtek Audio) [Loopback]",
                "defaultSampleRate": 48000.0,
                "maxInputChannels": 2,
            },
        ]

    def get_default_wasapi_loopback(self) -> dict[str, Any]:
        return dict(self._devices[1])

    def get_loopback_device_info_generator(self) -> Any:
        for dev in self._devices:
            yield dict(dev)

    def get_device_info_by_index(self, idx: int) -> dict[str, Any]:
        for dev in self._devices:
            if dev["index"] == idx:
                return dict(dev)
        raise ValueError(f"Unknown device index {idx}")

    def open(self, **kwargs: Any) -> _FakePortAudioStream:
        cb = kwargs.get("stream_callback")
        self.last_stream = _FakePortAudioStream(callback=cb)
        return self.last_stream

    def terminate(self) -> None:
        self.terminated = True


class CyclingAudioSampler:
    """Muestreador determinista que entrega una secuencia de fotogramas acusticos."""

    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self._frames = list(frames)
        self._idx = 0
        self.calls: list[tuple[int | None, str, float]] = []
        self.closed = False

    def list_audio_devices(self) -> list[dict[str, Any]]:
        return [
            {
                "index": 7,
                "name": "Speakers (Realtek Audio) [Loopback]",
                "label": "Default · Speakers (Realtek Audio) [Loopback] (48000 Hz)",
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
        self.calls.append((device_index, palette_mode, round(float(sensitivity), 2)))
        frame = self._frames[self._idx % len(self._frames)]
        self._idx += 1
        return dict(frame)

    def sample_audio_metrics(self) -> tuple[float, Color]:
        frame = self.sample_frame()
        return float(frame["rms"]), frame["color"]

    def close(self) -> None:
        self.closed = True


class CyclingScreenSampler:
    """Muestreador de pantalla minimo para probar la exclusion mutua entre Ambilight y Musica."""

    def sample_average_color(self, monitor_index: int = 1, mode: str = "vibrant") -> Color:
        return Color(40, 200, 120)

    def list_monitors(self) -> list[dict[str, Any]]:
        return [{"index": 1, "label": "Display 1 (1920x1080)", "width": 1920, "height": 1080}]


def test_analyze_pcm_audio_frame_silence_and_frequency_bands() -> None:
    """Verifica que la RFFT separe graves (80 Hz), medios (1000 Hz), agudos (6000 Hz) y silencio."""
    sample_rate = 48000

    # 1. Silencio absoluto: energia cero y brillo en el piso de cortesia (10-15%)
    silence = np.zeros(4096 * 2, dtype=np.float32)
    silent_metrics = analyze_pcm_audio_frame(silence, sample_rate=sample_rate, channels=2)
    assert silent_metrics["rms"] == 0.0
    assert silent_metrics["bass"] == 0.0
    assert silent_metrics["mid"] == 0.0
    assert silent_metrics["treble"] == 0.0
    assert 10 <= silent_metrics["brightness"] <= 15

    # 2. Onda grave de 80 Hz (bombo / sub-bass): domina la banda `bass` y el canal Rojo en spectrum
    bass_wave = _make_stereo_sine_wave(80.0, sample_rate=sample_rate)
    bass_metrics = analyze_pcm_audio_frame(
        bass_wave,
        sample_rate=sample_rate,
        channels=2,
        palette_mode="spectrum",
        sensitivity=1.0,
    )
    assert bass_metrics["bass"] > 0.75
    assert bass_metrics["bass"] > bass_metrics["mid"] * 5
    assert bass_metrics["bass"] > bass_metrics["treble"] * 5
    assert bass_metrics["brightness"] > 65
    bass_color: Color = bass_metrics["color"]
    assert bass_color.r > 200
    assert bass_color.r > bass_color.g * 3
    assert bass_color.r > bass_color.b * 3

    # 3. Onda media de 1000 Hz (voz / sintetizador): domina la banda `mid` y el canal Verde
    mid_wave = _make_stereo_sine_wave(1000.0, sample_rate=sample_rate)
    mid_metrics = analyze_pcm_audio_frame(
        mid_wave,
        sample_rate=sample_rate,
        channels=2,
        palette_mode="spectrum",
        sensitivity=1.0,
    )
    assert mid_metrics["mid"] > 0.70
    assert mid_metrics["mid"] > mid_metrics["bass"] * 5
    assert mid_metrics["mid"] > mid_metrics["treble"] * 5
    mid_color: Color = mid_metrics["color"]
    assert mid_color.g > 200
    assert mid_color.g > mid_color.r * 3
    assert mid_color.g > mid_color.b * 2

    # 4. Onda aguda de 6000 Hz (platillos / hi-hat): domina la banda `treble` y el canal Azul
    treble_wave = _make_stereo_sine_wave(6000.0, sample_rate=sample_rate)
    treble_metrics = analyze_pcm_audio_frame(
        treble_wave,
        sample_rate=sample_rate,
        channels=2,
        palette_mode="spectrum",
        sensitivity=1.0,
    )
    assert treble_metrics["treble"] > 0.70
    assert treble_metrics["treble"] > treble_metrics["bass"] * 5
    assert treble_metrics["treble"] > treble_metrics["mid"] * 5
    treble_color: Color = treble_metrics["color"]
    assert treble_color.b > 200
    assert treble_color.b > treble_color.r * 3
    assert treble_color.b > treble_color.g * 3

    # 5. Verificacion de paletas alternativas ("club" y "chill")
    club_metrics = analyze_pcm_audio_frame(
        bass_wave, sample_rate=sample_rate, channels=2, palette_mode="club"
    )
    chill_metrics = analyze_pcm_audio_frame(
        bass_wave, sample_rate=sample_rate, channels=2, palette_mode="chill"
    )
    assert club_metrics["color"] != chill_metrics["color"]
    assert club_metrics["color"].r > 180  # Graves en club producen magenta/carmesi
    assert chill_metrics["color"].b > 180  # Graves en chill producen azul oceano


def test_wasapi_loopback_sampler_non_blocking_silence_timeout() -> None:
    """Comprueba que WasapiLoopbackSampler cumpla AudioSampler y detecte silencio sin bloquear."""
    fake_pa = _FakePyAudioWPatch()
    sampler = WasapiLoopbackSampler(
        frames_per_buffer=1024,
        silence_timeout=0.06,
        pyaudio_factory=lambda: fake_pa,
    )
    assert isinstance(sampler, AudioSampler)

    devices = sampler.list_audio_devices()
    assert len(devices) == 2
    assert devices[0]["index"] == 7
    assert devices[0]["is_default"] is True

    # Antes de que WASAPI envie cualquier paquete (silencio inicial en Windows),
    # sample_frame devuelve silencio de inmediato sin bloquear.
    initial = sampler.sample_frame(palette_mode="spectrum", sensitivity=1.0)
    assert initial["rms"] == 0.0
    assert 10 <= initial["brightness"] <= 15
    assert fake_pa.last_stream is not None
    assert fake_pa.last_stream.started is True

    # Simulamos la llegada de un bloque de 80 Hz desde el hilo de audio de Windows
    bass_pcm = _make_stereo_sine_wave(80.0, num_frames=1024).tobytes()
    fake_pa.last_stream.callback(bass_pcm, 1024, {}, 0)

    active = sampler.sample_frame(palette_mode="spectrum", sensitivity=1.0)
    assert active["rms"] > 0.5
    assert active["bass"] > 0.7
    assert active["color"].r > 200

    # Si Windows detiene las interrupciones de audio (pausa musical > 60ms),
    # el adaptador cae automaticamente a silencio sin congelarse.
    time.sleep(0.08)
    after_pause = sampler.sample_frame(palette_mode="spectrum", sensitivity=1.0)
    assert after_pause["rms"] == 0.0
    assert after_pause["bass"] == 0.0
    assert 10 <= after_pause["brightness"] <= 15

    sampler.close()
    assert fake_pa.last_stream.closed is True
    assert fake_pa.terminated is True


async def test_music_sync_stream_and_mutual_exclusion_with_ambilight() -> None:
    """Verifica la emision UDP de Music Sync y la exclusion mutua frente a Ambilight y control manual."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        audio_sampler = CyclingAudioSampler(
            frames=[
                {
                    "rms": 0.75,
                    "bass": 0.90,
                    "mid": 0.25,
                    "treble": 0.15,
                    "brightness": 88,
                    "color": Color(245, 35, 60),
                },
                {
                    "rms": 0.65,
                    "bass": 0.20,
                    "mid": 0.85,
                    "treble": 0.30,
                    "brightness": 80,
                    "color": Color(30, 235, 95),
                },
                {
                    "rms": 0.80,
                    "bass": 0.15,
                    "mid": 0.30,
                    "treble": 0.92,
                    "brightness": 94,
                    "color": Color(35, 80, 250),
                },
            ]
        )
        screen_sampler = CyclingScreenSampler()
        limiter = StreamRateLimiter(max_hz=50.0, alpha=0.55, min_color_delta=1)
        ambi_mgr = AmbilightStreamManager(sampler=screen_sampler, interval_seconds=0.025)
        music_mgr = MusicSyncStreamManager(sampler=audio_sampler, interval_seconds=0.025)

        service = LightControlService(
            controller=controller,
            rate_limiter=limiter,
            screen_sampler=screen_sampler,
            ambilight_manager=ambi_mgr,
            audio_sampler=audio_sampler,
            music_manager=music_mgr,
        )

        await service.discover_bulbs()

        # 1. Iniciamos Ambilight primero
        ambi_status = service.start_ambilight(monitor_index=1, color_mode="vibrant")
        assert ambi_status["active"] is True
        assert service.get_music_sync_status()["active"] is False

        # 2. Al iniciar Music Sync, Ambilight debe detenerse automaticamente
        music_status = service.start_music_sync(
            palette_mode="club",
            sensitivity=1.2,
            smoothing_alpha=0.55,
            audio_brightness=True,
            brightness=85,
            device_index=7,
        )
        assert music_status["active"] is True
        assert music_status["palette_mode"] == "club"
        assert service.get_ambilight_status()["active"] is False

        await asyncio.sleep(0.11)

        live_music = service.get_music_sync_status()
        assert live_music["active"] is True
        assert live_music["frames_sent"] >= 2
        assert live_music["last_color"] is not None
        assert audio_sampler.calls[0] == (7, "club", 1.2)
        assert server.pilot_state["state"] is True
        assert "r" in server.pilot_state and "g" in server.pilot_state and "b" in server.pilot_state

        # 3. Si iniciamos Ambilight de nuevo, Music Sync debe detenerse automaticamente
        service.start_ambilight(monitor_index=1, color_mode="vibrant")
        assert service.get_ambilight_status()["active"] is True
        assert service.get_music_sync_status()["active"] is False

        # 4. Reiniciamos Music Sync y comprobamos que un comando manual lo detiene
        service.start_music_sync(palette_mode="spectrum")
        assert service.get_music_sync_status()["active"] is True
        await service.set_temperature(4000, brightness=70)
        assert service.get_music_sync_status()["active"] is False


async def test_webview_bridge_music_sync_lifecycle() -> None:
    """Comprueba start_music_sync, get_music_sync_status y stop_music_sync a traves de WebviewBridge."""
    async with FakeWizBulbServer(mac="a8bb50445566") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        audio_sampler = CyclingAudioSampler(
            frames=[
                {
                    "rms": 0.72,
                    "bass": 0.84,
                    "mid": 0.44,
                    "treble": 0.28,
                    "brightness": 86,
                    "color": Color(240, 50, 90),
                },
                {
                    "rms": 0.64,
                    "bass": 0.22,
                    "mid": 0.78,
                    "treble": 0.65,
                    "brightness": 78,
                    "color": Color(40, 190, 240),
                },
            ]
        )
        limiter = StreamRateLimiter(max_hz=40.0, alpha=0.5, min_color_delta=1)
        music_mgr = MusicSyncStreamManager(sampler=audio_sampler, interval_seconds=0.03)
        service = LightControlService(
            controller=controller,
            rate_limiter=limiter,
            audio_sampler=audio_sampler,
            music_manager=music_mgr,
            screen_sampler=MssScreenSampler(),
        )
        bridge = WebviewBridge(service=service)

        try:
            init_env = await asyncio.to_thread(bridge.get_initial_state)
            assert init_env["ok"] is True
            assert len(init_env["audio_devices"]) == 1
            assert init_env["music_sync"]["active"] is False

            started = await asyncio.to_thread(
                bridge.start_music_sync,
                "chill",
                1.4,
                0.50,
                False,
                65,
                7,
            )
            assert started["ok"] is True
            assert started["music_sync"]["active"] is True
            assert started["music_sync"]["palette_mode"] == "chill"
            assert started["music_sync"]["audio_brightness"] is False
            assert started["music_sync"]["brightness"] == 65

            await asyncio.sleep(0.09)

            polled = await asyncio.to_thread(bridge.get_music_sync_status)
            assert polled["ok"] is True
            assert polled["music_sync"]["active"] is True
            assert polled["music_sync"]["frames_sent"] >= 1
            assert polled["music_sync"]["bass"] > 0.0
            assert server.pilot_state["dimming"] == 65

            stopped = await asyncio.to_thread(bridge.stop_music_sync)
            assert stopped["ok"] is True
            assert stopped["music_sync"]["active"] is False
            assert stopped["music_sync"]["rms"] == 0.0
        finally:
            bridge.shutdown()
            assert audio_sampler.closed is True

