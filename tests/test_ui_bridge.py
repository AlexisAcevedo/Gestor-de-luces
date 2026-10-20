"""Pruebas de integracion para el adaptador primario WebviewBridge y main.py.

Verifica que el puente sincrono expuesto a PyWebView delegue correctamente todas
las operaciones hacia el bucle `asyncio` en segundo plano y se comunique por UDP
real con `FakeWizBulbServer`, devolviendo diccionarios JSON serializables con el
estado actualizado de los focos y las 36 escenas nativas de WiZ.
"""

from __future__ import annotations

import asyncio

from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService
from gestor_luces.main import main as run_main
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer


async def test_webview_bridge_full_lifecycle_over_udp() -> None:
    """Comprueba todas las operaciones del puente JS-Python contra dos focos UDP simulados."""
    async with (
        FakeWizBulbServer(mac="a8bb50112201") as server_one,
        FakeWizBulbServer(mac="a8bb50112202") as server_two,
    ):
        ep_one = server_one.endpoint
        ep_two = server_two.endpoint

        controller = WizUdpController(probe_candidates=[ep_one, ep_two])
        service = LightControlService(controller=controller)
        bridge = WebviewBridge(service=service)

        try:
            # 1. Estado inicial: descubre los focos automaticamente y devuelve las 36 escenas
            initial = await asyncio.to_thread(bridge.get_initial_state)
            assert initial["ok"] is True
            assert initial["error"] is None
            assert len(initial["scenes"]) == 36
            assert len(initial["bulbs"]) == 2
            assert set(initial["selected_ips"]) == {ep_one, ep_two}

            # 2. Renombrar foco y comprobar serializacion
            renamed = await asyncio.to_thread(bridge.rename_bulb, ep_one, "Desk Key Light")
            assert renamed["ok"] is True
            bulb_one_dict = next(b for b in renamed["bulbs"] if b["ip"] == ep_one)
            assert bulb_one_dict["name"] == "Desk Key Light"

            # 3. Encendido y ajuste de brillo maestro
            powered = await asyncio.to_thread(bridge.set_power, True, 75)
            assert powered["ok"] is True
            assert server_one.pilot_state["state"] is True
            assert server_one.pilot_state["dimming"] == 75
            assert server_two.pilot_state["state"] is True
            assert server_two.pilot_state["dimming"] == 75

            dimmed = await asyncio.to_thread(bridge.set_brightness, 40)
            assert dimmed["ok"] is True
            assert server_one.pilot_state["dimming"] == 40
            assert server_two.pilot_state["dimming"] == 40

            # 4. Seleccion de un unico foco y cambio a modo RGB
            selected = await asyncio.to_thread(bridge.select_targets, [ep_one])
            assert selected["ok"] is True
            assert selected["selected_ips"] == [ep_one]

            colored = await asyncio.to_thread(bridge.set_color, 255, 64, 128, 90)
            assert colored["ok"] is True
            assert (
                server_one.pilot_state["r"],
                server_one.pilot_state["g"],
                server_one.pilot_state["b"],
            ) == (255, 64, 128)
            assert server_one.pilot_state["dimming"] == 90
            # El segundo foco no estaba seleccionado, conserva su brillo anterior
            assert server_two.pilot_state["dimming"] == 40

            # 5. Seleccion de ambos focos y cambio a temperatura Kelvin
            await asyncio.to_thread(bridge.select_targets, [ep_one, ep_two])
            kelvin_res = await asyncio.to_thread(bridge.set_temperature, 3200, 85)
            assert kelvin_res["ok"] is True
            assert server_one.pilot_state["temp"] == 3200
            assert server_two.pilot_state["temp"] == 3200

            # 6. Activacion de escena dinamica nativa (Ocean = ID 1) con velocidad 135
            scene_res = await asyncio.to_thread(bridge.set_builtin_scene, 1, 135, 95)
            assert scene_res["ok"] is True
            assert server_one.pilot_state["sceneId"] == 1
            assert server_one.pilot_state["speed"] == 135
            assert server_two.pilot_state["sceneId"] == 1
            assert server_two.pilot_state["speed"] == 135

            # 7. Sincronizacion en vivo (refresh_states) tras cambio externo en el foco 2
            server_two.pilot_state.update(
                {
                    "state": False,
                    "dimming": 20,
                    "sceneId": 0,
                    "temp": 2700,
                }
            )
            refreshed = await asyncio.to_thread(bridge.refresh_states)
            assert refreshed["ok"] is True
            bulb_two_dict = next(b for b in refreshed["bulbs"] if b["ip"] == ep_two)
            assert bulb_two_dict["state"]["is_on"] is False
            assert bulb_two_dict["state"]["brightness"] == 20
        finally:
            bridge.shutdown()


async def test_webview_bridge_manual_bulb_and_validation_errors() -> None:
    """Verifica el alta manual por IP y el manejo limpio de errores de validacion."""
    async with FakeWizBulbServer(mac="a8bb50998877") as server:
        controller = WizUdpController(probe_candidates=[])
        service = LightControlService(controller=controller)
        bridge = WebviewBridge(service=service)

        try:
            added = await asyncio.to_thread(
                bridge.add_manual_bulb,
                server.endpoint,
                "Hallway Spotlight",
            )
            assert added["ok"] is True
            assert len(added["bulbs"]) == 1
            assert added["bulbs"][0]["name"] == "Hallway Spotlight"
            assert added["bulbs"][0]["mac"] == "a8bb50998877"

            # Un valor fuera de rango debe devolver ok=False con el detalle del error
            invalid_temp = await asyncio.to_thread(bridge.set_temperature, 9999)
            assert invalid_temp["ok"] is False
            assert invalid_temp["error"] is not None
        finally:
            bridge.shutdown()


def test_main_composition_root_smoke_test() -> None:
    """Ejecuta el smoke test del punto de entrada principal para validar rutas y ensamblado."""
    exit_code = run_main(["--smoke-test"])
    assert exit_code == 0
