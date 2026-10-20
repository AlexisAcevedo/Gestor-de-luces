"""Pruebas unitarias y de integracion para el modo Ambilight (Fase 6).

Cubre:
1. Extraccion cromatica BGRA a RGB (`average` vs `vibrant`) y calculo de luminancia
   ITU-R BT.709 en `MssScreenSampler` usando buffers sinteticos deterministas.
2. Enumeracion de monitores individuales y combinados (`list_monitors`).
3. Flujo continuo asincrono (`AmbilightStreamManager` + `LightControlService` +
   `WizUdpController`) contra `FakeWizBulbServer` sobre sockets UDP reales.
4. Precedencia del control manual (apagado, cambio de color, Kelvin o escena) que
   detiene automaticamente el flujo Ambilight para evitar conflictos.
5. Exposicion del estado y controles de Ambilight a traves de `WebviewBridge`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import numpy as np

from gestor_luces.adapters.ambilight import (
    MssScreenSampler,
    extract_color_and_brightness_from_bgra,
)
from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.ambilight_stream import AmbilightStreamManager
from gestor_luces.application.rate_limiter import StreamRateLimiter
from gestor_luces.application.service import LightControlService
from gestor_luces.domain.value_objects import Color
from gestor_luces.ports.interfaces import ScreenSampler
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer


@dataclass
class _FakeMssShot:
    """Emula el objeto `ScreenShot` devuelto por `mss.grab()` con un buffer BGRA."""

    bgra: bytes
    width: int
    height: int


class _FakeMssContext:
    """Simulador determinista de `mss.mss()` para probar el adaptador sin pantalla fisica."""

    def __init__(self, monitors: list[dict[str, int]], shot: _FakeMssShot) -> None:
        self.monitors = monitors
        self._shot = shot
        self.grabbed_monitors: list[dict[str, int]] = []

    def __enter__(self) -> _FakeMssContext:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def grab(self, monitor: dict[str, int]) -> _FakeMssShot:
        self.grabbed_monitors.append(monitor)
        return self._shot


class CyclingScreenSampler:
    """Muestreador determinista que entrega una secuencia de colores para pruebas de flujo."""

    def __init__(self, frames: list[tuple[Color, int]]) -> None:
        self._frames = list(frames)
        self._idx = 0
        self.calls: list[tuple[int, str]] = []

    def list_monitors(self) -> list[dict[str, Any]]:
        return [
            {"index": 1, "label": "Display 1 (2560x1440)", "width": 2560, "height": 1440},
            {"index": 2, "label": "Display 2 (1920x1080)", "width": 1920, "height": 1080},
            {"index": 0, "label": "All displays (4480x1440)", "width": 4480, "height": 1440},
        ]

    def sample_frame(self, monitor_index: int = 1, mode: str = "vibrant") -> tuple[Color, int]:
        self.calls.append((monitor_index, mode))
        frame = self._frames[self._idx % len(self._frames)]
        self._idx += 1
        return frame

    def sample_average_color(self, monitor_index: int = 1, mode: str = "average") -> Color:
        color, _ = self.sample_frame(monitor_index=monitor_index, mode=mode)
        return color


def test_bgra_extraction_respects_channel_order_and_modes() -> None:
    """Comprueba que el canal 0 se lea como Azul y el canal 2 como Rojo, y compara average vs vibrant."""
    width, height = 32, 32
    # Construimos un cuadro donde el 75% de los pixeles son gris oscuro neutro (30, 30, 30)
    # y el 25% restante es rojo intenso (R=250, G=20, B=10 -> en orden BGRA: 10, 20, 250, 255).
    frame = np.zeros((height, width, 4), dtype=np.uint8)
    frame[:, :, 0] = 30  # Blue
    frame[:, :, 1] = 30  # Green
    frame[:, :, 2] = 30  # Red
    frame[:, :, 3] = 255

    # Cuadrante superior izquierdo (25% del area) en rojo vibrante
    frame[:16, :16, 0] = 10   # Blue
    frame[:16, :16, 1] = 20   # Green
    frame[:16, :16, 2] = 250  # Red

    bgra_bytes = frame.tobytes()

    avg_color, avg_bri = extract_color_and_brightness_from_bgra(
        bgra_bytes, width=width, height=height, mode="average", stride=1
    )
    vib_color, vib_bri = extract_color_and_brightness_from_bgra(
        bgra_bytes, width=width, height=height, mode="vibrant", stride=1
    )

    # En modo promedio: R = 0.75*30 + 0.25*250 = 85
    assert avg_color == Color(r=85, g=28, b=25)
    assert 10 <= avg_bri <= 100
    assert avg_bri == vib_bri

    # En modo vibrante, los pixeles saturados pesan mucho mas que el fondo gris oscuro
    assert vib_color.r > 200
    assert vib_color.r > avg_color.r * 2
    assert vib_color.g < 30
    assert vib_color.b < 20


def test_mss_screen_sampler_implements_protocol_and_lists_monitors() -> None:
    """Verifica que MssScreenSampler cumpla ScreenSampler y enumere monitores correctamente."""
    pixel_bgra = bytes([200, 100, 50, 255]) * (16 * 16)  # B=200, G=100, R=50
    shot = _FakeMssShot(bgra=pixel_bgra, width=16, height=16)
    fake_monitors = [
        {"left": 0, "top": 0, "width": 3840, "height": 1080},
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 1920, "top": 0, "width": 1920, "height": 1080},
    ]
    ctx = _FakeMssContext(monitors=fake_monitors, shot=shot)
    sampler = MssScreenSampler(stride=4, sct_factory=lambda: ctx)

    assert isinstance(sampler, ScreenSampler)

    monitors = sampler.list_monitors()
    assert len(monitors) == 3
    assert monitors[0]["index"] == 1
    assert "1920x1080" in monitors[0]["label"]
    assert monitors[1]["index"] == 2
    assert monitors[2]["index"] == 0
    assert "All displays" in monitors[2]["label"]

    sampled = sampler.sample_average_color(monitor_index=2, mode="average")
    assert sampled == Color(r=50, g=100, b=200)
    assert ctx.grabbed_monitors[-1] == fake_monitors[2]


async def test_ambilight_stream_and_manual_override_over_udp() -> None:
    """Verifica que Ambilight transmita paquetes UDP continuos y se detenga ante un cambio manual."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        sampler = CyclingScreenSampler(
            frames=[
                (Color(240, 30, 60), 80),
                (Color(20, 190, 250), 90),
                (Color(40, 240, 100), 75),
            ]
        )
        limiter = StreamRateLimiter(max_hz=50.0, alpha=0.5, min_color_delta=1)
        ambi_mgr = AmbilightStreamManager(sampler=sampler, interval_seconds=0.025)
        service = LightControlService(
            controller=controller,
            rate_limiter=limiter,
            screen_sampler=sampler,
            ambilight_manager=ambi_mgr,
        )

        await service.discover_bulbs()

        status = service.start_ambilight(
            monitor_index=2,
            color_mode="vibrant",
            auto_brightness=True,
            brightness=85,
            smoothing_alpha=0.5,
        )
        assert status["active"] is True
        assert status["monitor_index"] == 2
        assert status["color_mode"] == "vibrant"

        # Dejamos correr varias iteraciones del bucle de muestreo a 25ms
        await asyncio.sleep(0.12)

        live_status = service.get_ambilight_status()
        assert live_status["active"] is True
        assert live_status["frames_sent"] >= 2
        assert live_status["last_color"] is not None
        assert sampler.calls[0] == (2, "vibrant")

        # El servidor UDP simulado debe haber recibido paquetes setPilot con canales RGB
        assert server.pilot_state["state"] is True
        assert "r" in server.pilot_state and "g" in server.pilot_state and "b" in server.pilot_state

        # Si el usuario aplica manualmente una temperatura Kelvin, Ambilight se detiene solo
        await service.set_temperature(3200, brightness=60)
        assert service.get_ambilight_status()["active"] is False
        assert server.pilot_state["temp"] == 3200


async def test_webview_bridge_ambilight_lifecycle() -> None:
    """Comprueba start_ambilight, get_ambilight_status y stop_ambilight a traves de WebviewBridge."""
    async with FakeWizBulbServer(mac="a8bb50112233") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        sampler = CyclingScreenSampler(
            frames=[
                (Color(180, 40, 240), 85),
                (Color(250, 140, 20), 90),
            ]
        )
        limiter = StreamRateLimiter(max_hz=40.0, alpha=0.45, min_color_delta=1)
        ambi_mgr = AmbilightStreamManager(sampler=sampler, interval_seconds=0.03)
        service = LightControlService(
            controller=controller,
            rate_limiter=limiter,
            screen_sampler=sampler,
            ambilight_manager=ambi_mgr,
        )
        bridge = WebviewBridge(service=service)

        try:
            init_env = await asyncio.to_thread(bridge.get_initial_state)
            assert init_env["ok"] is True
            assert len(init_env["monitors"]) == 3
            assert init_env["ambilight"]["active"] is False

            started = await asyncio.to_thread(
                bridge.start_ambilight,
                1,
                "vibrant",
                False,
                70,
                0.45,
                None,
                16,
            )
            assert started["ok"] is True
            assert started["ambilight"]["active"] is True
            assert started["ambilight"]["auto_brightness"] is False
            assert started["ambilight"]["brightness"] == 70
            assert started["ambilight"]["min_brightness"] == 16

            await asyncio.sleep(0.09)

            polled = await asyncio.to_thread(bridge.get_ambilight_status)
            assert polled["ok"] is True
            assert polled["ambilight"]["active"] is True
            assert polled["ambilight"]["frames_sent"] >= 1
            assert polled["ambilight"]["min_brightness"] == 16
            assert server.pilot_state["dimming"] == 70

            stopped = await asyncio.to_thread(bridge.stop_ambilight)
            assert stopped["ok"] is True
            assert stopped["ambilight"]["active"] is False
        finally:
            bridge.shutdown()


async def test_ambilight_auto_brightness_respects_min_brightness_floor() -> None:
    """Verifica que el piso de brillo minimo (min_brightness) eleve escenas oscuras con auto_brightness=True."""
    async with FakeWizBulbServer(mac="a8bb50998877") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        # Cuadro muy oscuro con luminancia sugerida del 10%
        sampler = CyclingScreenSampler(frames=[(Color(15, 10, 20), 10)])
        limiter = StreamRateLimiter(max_hz=40.0, alpha=1.0, min_color_delta=1)
        ambi_mgr = AmbilightStreamManager(sampler=sampler, interval_seconds=0.025)
        service = LightControlService(
            controller=controller,
            rate_limiter=limiter,
            screen_sampler=sampler,
            ambilight_manager=ambi_mgr,
        )

        await service.discover_bulbs()
        status = service.start_ambilight(
            monitor_index=1,
            color_mode="vibrant",
            auto_brightness=True,
            brightness=85,
            smoothing_alpha=1.0,
            min_brightness=18,
        )
        assert status["min_brightness"] == 18

        await asyncio.sleep(0.08)
        await service.stop_ambilight()

        # Aunque el sampler sugiera 10%, el piso configurado de 18% debe imponerse
        assert server.pilot_state["dimming"] == 18

