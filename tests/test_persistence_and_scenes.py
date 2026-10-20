"""Pruebas de persistencia JSON, escenas personalizadas y temporizador de apagado.

Verifica que:
1. JsonBulbRepository y JsonSceneRepository escriban archivos JSON de forma atomica
   en un directorio temporal (`tmp_path`), preserven todos los modos (RGB, Kelvin,
   escenas nativas) y se recuperen sin fallar ante archivos inexistentes o corruptos.
2. LightControlService capture el estado luminico actual en un CustomScene, permita
   renombrarlo, aplicarlo sobre focos UDP simulados (`FakeWizBulbServer`) y eliminarlo.
3. SleepTimerManager y LightControlService ejecuten la atenuacion progresiva de brillo
   y apaguen los focos al expirar el tiempo, ademas de soportar cancelacion limpia.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from gestor_luces.adapters.storage.json_repositories import (
    JsonBulbRepository,
    JsonSceneRepository,
)
from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService
from gestor_luces.domain.models import Bulb, LightState
from gestor_luces.domain.scenes import CustomScene
from gestor_luces.domain.value_objects import Color, LightMode
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer


def test_json_repositories_round_trip_and_corruption_resilience(tmp_path: Path) -> None:
    """Comprueba el guardado/carga en JSON y la tolerancia frente a archivos corruptos."""
    bulb_repo = JsonBulbRepository(data_dir=tmp_path)
    scene_repo = JsonSceneRepository(data_dir=tmp_path)

    # Cuando los archivos aun no existen, ambos repositorios devuelven listas vacias
    assert bulb_repo.load_bulbs() == []
    assert scene_repo.load_scenes() == []

    # Guardado y recarga de focos con distintos modos y nombres personalizados
    bulbs_to_save = [
        Bulb(
            ip="192.168.0.34",
            mac="a8bb50df9029",
            name="Escritorio Principal",
            is_online=True,
            state=LightState(
                is_on=True,
                brightness=85,
                mode=LightMode.RGB,
                color=Color(0, 180, 255),
                temperature=None,
            ),
        ),
        Bulb(
            ip="192.168.0.35",
            mac="a8bb50df9030",
            name="Velador Dormitorio",
            is_online=False,
            state=LightState(
                is_on=False,
                brightness=40,
                mode=LightMode.TEMPERATURE,
                temperature=2700,
            ),
        ),
    ]
    bulb_repo.save_bulbs(bulbs_to_save)
    assert bulb_repo.file_path.is_file()

    loaded_bulbs = bulb_repo.load_bulbs()
    assert len(loaded_bulbs) == 2
    assert loaded_bulbs[0].name == "Escritorio Principal"
    assert loaded_bulbs[0].state.mode == LightMode.RGB
    assert loaded_bulbs[0].state.color == Color(0, 180, 255)
    assert loaded_bulbs[1].name == "Velador Dormitorio"
    assert loaded_bulbs[1].state.temperature == 2700

    # Guardado y recarga de escenas personalizadas de los 3 modos
    scenes_to_save = [
        CustomScene(
            id="sc_rgb",
            name="Cyberpunk Cyan",
            mode=LightMode.RGB,
            brightness=90,
            color=Color(0, 240, 255),
        ),
        CustomScene(
            id="sc_temp",
            name="Warm Reading",
            mode=LightMode.TEMPERATURE,
            brightness=65,
            temperature=3000,
        ),
        CustomScene(
            id="sc_wiz",
            name="Fast Ocean",
            mode=LightMode.SCENE,
            brightness=80,
            built_in_scene_id=1,
            speed=160,
        ),
    ]
    scene_repo.save_scenes(scenes_to_save)
    assert scene_repo.file_path.is_file()

    loaded_scenes = scene_repo.load_scenes()
    assert len(loaded_scenes) == 3
    assert loaded_scenes[0].color == Color(0, 240, 255)
    assert loaded_scenes[1].temperature == 3000
    assert loaded_scenes[2].built_in_scene_id == 1
    assert loaded_scenes[2].speed == 160

    # Si un archivo se corrompe en disco, la carga no lanza excepcion y devuelve []
    bulb_repo.file_path.write_text("{corrupted_json: [", encoding="utf-8")
    scene_repo.file_path.write_text("not valid json", encoding="utf-8")
    assert bulb_repo.load_bulbs() == []
    assert scene_repo.load_scenes() == []


async def test_custom_scenes_lifecycle_and_udp_application(tmp_path: Path) -> None:
    """Verifica crear, renombrar, aplicar por UDP y eliminar escenas personalizadas."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        bulb_repo = JsonBulbRepository(data_dir=tmp_path)
        scene_repo = JsonSceneRepository(data_dir=tmp_path)
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(
            controller=controller,
            bulb_repository=bulb_repo,
            scene_repository=scene_repo,
        )

        await service.discover_bulbs()

        # 1. Configuramos el foco en un color RGB especifico y guardamos el estado como preset
        await service.set_color(180, 40, 240, brightness=75)
        saved_scene = service.save_custom_scene_from_current(name="Neon Studio")
        assert saved_scene.name == "Neon Studio"
        assert saved_scene.mode == LightMode.RGB
        assert saved_scene.color == Color(180, 40, 240)
        assert saved_scene.brightness == 75
        assert len(scene_repo.load_scenes()) == 1

        # 2. Renombramos el preset y comprobamos que se persiste en custom_scenes.json
        renamed = service.rename_custom_scene(saved_scene.id, "Deep Violet")
        assert renamed.name == "Deep Violet"
        assert scene_repo.load_scenes()[0].name == "Deep Violet"

        # 3. Cambiamos el foco a temperatura blanca (5000K) y luego reaplicamos el preset
        await service.set_temperature(5000, brightness=30)
        assert server.pilot_state["temp"] == 5000
        assert server.pilot_state["dimming"] == 30

        await service.apply_custom_scene(saved_scene.id)
        assert (
            server.pilot_state["r"],
            server.pilot_state["g"],
            server.pilot_state["b"],
        ) == (180, 40, 240)
        assert server.pilot_state["dimming"] == 75

        # 4. Eliminamos el preset y verificamos que desaparece de memoria y disco
        service.delete_custom_scene(saved_scene.id)
        assert service.list_custom_scenes() == []
        assert scene_repo.load_scenes() == []


async def test_sleep_timer_progressive_dimming_and_power_off(tmp_path: Path) -> None:
    """Comprueba que el Sleep Timer atenue el brillo progresivamente y apague el foco."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(
            controller=controller,
            bulb_repository=JsonBulbRepository(data_dir=tmp_path),
            scene_repository=JsonSceneRepository(data_dir=tmp_path),
        )
        await service.discover_bulbs()
        await service.set_power(is_on=True, brightness=90)
        assert server.pilot_state["state"] is True
        assert server.pilot_state["dimming"] == 90

        # Registramos los valores de dimming enviados durante la cuenta regresiva
        observed_dimming: list[int] = []
        original_set_brightness = controller.set_brightness

        async def _spy_set_brightness(ip: str, brightness: int) -> bool:
            observed_dimming.append(brightness)
            return await original_set_brightness(ip, brightness=brightness)

        controller.set_brightness = _spy_set_brightness  # type: ignore[method-assign]

        # Iniciamos un temporizador breve de 0.005 minutos (0.3 segundos)
        status = await service.start_sleep_timer(minutes=0.005)
        assert status["active"] is True
        assert status["remaining_seconds"] >= 1

        # Esperamos a que complete la cuenta regresiva y los pasos de atenuacion
        await asyncio.sleep(0.45)

        final_status = service.get_sleep_timer_status()
        assert final_status["active"] is False
        assert len(observed_dimming) >= 2
        assert observed_dimming[-1] == 10
        assert server.pilot_state["state"] is False


async def test_sleep_timer_cancellation_keeps_bulb_on() -> None:
    """Verifica que cancelar el Sleep Timer detenga la cuenta regresiva sin apagar el foco."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(controller=controller)
        await service.discover_bulbs()
        await service.set_power(is_on=True, brightness=80)

        status = service.start_sleep_timer(minutes=0.02)
        assert status["active"] is True

        cancelled = service.cancel_sleep_timer()
        assert cancelled["active"] is False
        assert cancelled["remaining_seconds"] == 0

        await asyncio.sleep(0.15)
        assert server.pilot_state["state"] is True


async def test_webview_bridge_custom_scenes_and_sleep_timer(tmp_path: Path) -> None:
    """Verifica los nuevos metodos de fase 4 expuestos en WebviewBridge."""
    async with FakeWizBulbServer(mac="a8bb50df9029") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(
            controller=controller,
            bulb_repository=JsonBulbRepository(data_dir=tmp_path),
            scene_repository=JsonSceneRepository(data_dir=tmp_path),
        )
        bridge = WebviewBridge(service=service)

        try:
            await asyncio.to_thread(bridge.get_initial_state)
            await asyncio.to_thread(bridge.set_color, 20, 200, 120, 85)

            saved_env = await asyncio.to_thread(bridge.save_custom_scene, "Emerald Glow")
            assert saved_env["ok"] is True
            assert len(saved_env["custom_scenes"]) == 1
            preset_id = saved_env["custom_scenes"][0]["id"]

            updated_env = await asyncio.to_thread(
                bridge.update_custom_scene,
                preset_id,
                "Studio Emerald",
                False,
            )
            assert updated_env["ok"] is True
            assert updated_env["custom_scenes"][0]["name"] == "Studio Emerald"

            await asyncio.to_thread(bridge.set_temperature, 2700, 40)
            applied_env = await asyncio.to_thread(bridge.apply_custom_scene, preset_id)
            assert applied_env["ok"] is True
            assert server.pilot_state["g"] == 200

            timer_env = await asyncio.to_thread(bridge.start_sleep_timer, 15)
            assert timer_env["ok"] is True
            assert timer_env["sleep_timer"]["active"] is True

            cancelled_env = await asyncio.to_thread(bridge.cancel_sleep_timer)
            assert cancelled_env["ok"] is True
            assert cancelled_env["sleep_timer"]["active"] is False

            deleted_env = await asyncio.to_thread(bridge.delete_custom_scene, preset_id)
            assert deleted_env["ok"] is True
            assert deleted_env["custom_scenes"] == []
        finally:
            bridge.shutdown()
