"""Pruebas de integracion UDP: LightControlService + WizUdpController + FakeWizBulbServer.

Verifica que toda la pila de control (casos de uso + adaptador UDP) descubra,
controle multiples focos a la vez o individualmente, aplique colores RGB,
temperaturas Kelvin, escenas con velocidad, sincronice cambios externos mediante
getPilot y emita flujos continuos limitados por frecuencia sobre sockets UDP reales.
"""

from __future__ import annotations

import asyncio

from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.rate_limiter import StreamRateLimiter
from gestor_luces.application.service import LightControlService
from gestor_luces.domain.models import Bulb
from gestor_luces.domain.value_objects import Color, LightMode
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer


class InMemoryBulbRepository:
    """Repositorio en memoria que implementa BulbRepository para verificar la persistencia."""

    def __init__(self) -> None:
        self.saved: list[Bulb] = []

    def load_bulbs(self) -> list[Bulb]:
        return list(self.saved)

    def save_bulbs(self, bulbs: list[Bulb]) -> None:
        self.saved = list(bulbs)


async def test_multi_bulb_discovery_and_control_over_udp() -> None:
    """Comprueba el control simultaneo e individual de dos focos simulados por UDP."""
    async with (
        FakeWizBulbServer(mac="a8bb50000001") as server_one,
        FakeWizBulbServer(mac="a8bb50000002") as server_two,
    ):
        ep_one = server_one.endpoint
        ep_two = server_two.endpoint

        repo = InMemoryBulbRepository()
        controller = WizUdpController(probe_candidates=[ep_one, ep_two])
        service = LightControlService(controller=controller, bulb_repository=repo)

        # 1. Descubrimiento de ambos focos en la red simulada
        bulbs = await service.discover_bulbs()
        assert len(bulbs) == 2
        assert {b.mac for b in bulbs} == {"a8bb50000001", "a8bb50000002"}
        assert len(repo.saved) == 2

        # 2. Renombrar el primer foco y verificar que se guarda en el repositorio
        renamed = service.rename_bulb(ep_one, "Lampara Escritorio")
        assert renamed.name == "Lampara Escritorio"

        # 3. Encender ambos focos en simultaneo al 80% de brillo
        await service.set_power(is_on=True, brightness=80)
        assert server_one.pilot_state["state"] is True
        assert server_one.pilot_state["dimming"] == 80
        assert server_two.pilot_state["state"] is True
        assert server_two.pilot_state["dimming"] == 80

        # 4. Aplicar color RGB unicamente al primer foco (seleccion individual)
        service.select_targets([ep_one])
        await service.set_color(120, 40, 250, brightness=90)
        assert (
            server_one.pilot_state["r"],
            server_one.pilot_state["g"],
            server_one.pilot_state["b"],
        ) == (120, 40, 250)
        assert server_one.pilot_state["dimming"] == 90
        # El segundo foco permanece sin cambios en modo temperatura
        assert "r" not in server_two.pilot_state

        # 5. Seleccionar ambos focos y aplicar temperatura calida 2700K
        service.select_targets([ep_one, ep_two])
        await service.set_temperature(2700, brightness=65)
        for srv in (server_one, server_two):
            assert srv.pilot_state["temp"] == 2700
            assert srv.pilot_state["dimming"] == 65
            assert "r" not in srv.pilot_state

        # 6. Activar escena dinamica (Party = ID 4) con velocidad 150
        updated_bulbs = await service.set_builtin_scene(scene_id=4, speed=150, brightness=95)
        for srv in (server_one, server_two):
            assert srv.pilot_state["sceneId"] == 4
            assert srv.pilot_state["speed"] == 150
            assert srv.pilot_state["dimming"] == 95
        assert all(b.state.scene_name == "Party" for b in updated_bulbs)


async def test_live_state_sync_detects_external_changes() -> None:
    """Verifica que refresh_states refleje cambios hechos fuera de la app (ej. app movil)."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        controller = WizUdpController()
        service = LightControlService(controller=controller)
        await service.add_manual_bulb(server.endpoint, name="Dormitorio")

        # Simulamos que el usuario cambia el foco a verde desde su telefono movil
        server.pilot_state.update(
            {
                "state": True,
                "dimming": 45,
                "r": 10,
                "g": 240,
                "b": 30,
                "sceneId": 0,
            }
        )
        server.pilot_state.pop("temp", None)

        refreshed = await service.refresh_states()
        assert len(refreshed) == 1
        state = refreshed[0].state
        assert state.is_on is True
        assert state.brightness == 45
        assert state.mode == LightMode.RGB
        assert state.color == Color(10, 240, 30)


async def test_stream_color_frame_sends_udp_datagrams() -> None:
    """Verifica el envio de fotogramas fire-and-forget para Ambilight/Musica."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        controller = WizUdpController()
        limiter = StreamRateLimiter(max_hz=10.0, alpha=1.0)
        service = LightControlService(controller=controller, rate_limiter=limiter)
        await service.add_manual_bulb(server.endpoint)

        sent = await service.stream_color_frame(Color(255, 128, 0), brightness=70)
        assert sent is True

        # Damos una breve ventana al event loop para que el datagrama UDP local llegue
        await asyncio.sleep(0.03)
        assert server.pilot_state["r"] == 255
        assert server.pilot_state["g"] == 128
        assert server.pilot_state["b"] == 0
        assert server.pilot_state["dimming"] == 70
