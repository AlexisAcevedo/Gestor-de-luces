"""Pruebas de integracion UDP: LightControlService + WizUdpController + FakeWizBulbServer.

Verifica que toda la pila de control (casos de uso + adaptador UDP) descubra,
controle multiples focos a la vez o individualmente, aplique colores RGB,
temperaturas Kelvin, escenas con velocidad, sincronice cambios externos mediante
getPilot y emita flujos continuos limitados por frecuencia sobre sockets UDP reales.
"""

from __future__ import annotations

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from tests.waits import wait_until
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.rate_limiter import StreamRateLimiter
from wiz_console.application.service import LightControlService
from wiz_console.domain.models import Bulb
from wiz_console.domain.value_objects import Color, LightMode


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

        # El datagrama UDP local llega cuando llega: se espera la condicion observable.
        wait_until(
            lambda: server.pilot_state.get("r") == 255,
            "the simulated bulb never received the streamed color",
        )
        assert server.pilot_state["r"] == 255
        assert server.pilot_state["g"] == 128
        assert server.pilot_state["b"] == 0
        assert server.pilot_state["dimming"] == 70


async def test_remove_bulb_updates_targets_and_persistence() -> None:
    """remove_bulb deletes a bulb, updates selected targets/repository, and rejects unknown IPs."""
    import pytest

    async with (
        FakeWizBulbServer(mac="a8bb50000011") as srv1,
        FakeWizBulbServer(mac="a8bb50000012") as srv2,
    ):
        repo = InMemoryBulbRepository()
        controller = WizUdpController(probe_candidates=[srv1.endpoint, srv2.endpoint])
        service = LightControlService(controller=controller, bulb_repository=repo)
        await service.discover_bulbs()

        removed = service.remove_bulb(srv1.endpoint)
        assert removed.ip == srv1.endpoint
        assert [b.ip for b in service.list_bulbs()] == [srv2.endpoint]
        assert service.get_target_ips() == [srv2.endpoint]
        assert [b.ip for b in repo.saved] == [srv2.endpoint]

        with pytest.raises(KeyError):
            service.remove_bulb(srv1.endpoint)


async def test_discover_bulbs_reconciles_dhcp_ip_change_by_mac() -> None:
    """DHCP IP changes for a known MAC migrate the entry and keep custom alias & selection."""
    from dataclasses import replace

    from wiz_console.domain.models import LightState

    class _MockController:
        def __init__(self, bulbs: list[Bulb]) -> None:
            self.bulbs = bulbs

        async def discover(self, wait_time: float = 2.5) -> list[Bulb]:
            return [replace(b) for b in self.bulbs]

        async def probe_bulb(self, ip: str) -> Bulb | None:
            return next((replace(b) for b in self.bulbs if b.ip == ip), None)

        async def get_state(self, ip: str) -> LightState | None:
            b = next((b for b in self.bulbs if b.ip == ip), None)
            return b.state if b else None

        async def set_power(self, ip: str, is_on: bool, brightness: int | None = None) -> bool:
            return True

        async def set_brightness(self, ip: str, brightness: int) -> bool:
            return True

        async def set_color(self, ip: str, color: Color, brightness: int | None = None) -> bool:
            return True

        async def set_temperature(
            self, ip: str, temperature: int, brightness: int | None = None
        ) -> bool:
            return True

        async def set_scene(
            self, ip: str, scene_id: int, speed: int = 100, brightness: int | None = None
        ) -> bool:
            return True

        async def stream_pilot(
            self, ip: str, color: Color | None = None, brightness: int | None = None
        ) -> bool:
            return True

        async def close(self) -> None:
            return None

    repo = InMemoryBulbRepository()
    ctrl = _MockController(
        [
            Bulb(ip="192.168.1.10", mac="AA:BB:CC:00:00:01", name="WiZ Bulb (192.168.1.10)"),
            Bulb(ip="192.168.1.11", mac="unknown", name="Guest Lamp"),
        ]
    )
    service = LightControlService(controller=ctrl, bulb_repository=repo)
    await service.discover_bulbs()
    service.rename_bulb("192.168.1.10", "Studio Key")
    service.select_targets(["192.168.1.10"])

    # Simulate DHCP lease change for Studio Key plus another bulb with "unknown" MAC.
    ctrl.bulbs = [
        Bulb(ip="192.168.1.44", mac="aabbcc000001", name="WiZ Bulb (192.168.1.44)"),
        Bulb(ip="192.168.1.99", mac="unknown", name="WiZ Bulb (192.168.1.99)"),
    ]
    bulbs = await service.discover_bulbs()
    ips = {b.ip for b in bulbs}
    assert "192.168.1.10" not in ips
    assert "192.168.1.44" in ips
    assert "192.168.1.11" in ips  # unknown MAC is never treated as a duplicate match
    assert "192.168.1.99" in ips
    reconciled = service.get_bulb("192.168.1.44")
    assert reconciled is not None
    assert reconciled.name == "Studio Key"
    assert service.get_target_ips() == ["192.168.1.44"]
