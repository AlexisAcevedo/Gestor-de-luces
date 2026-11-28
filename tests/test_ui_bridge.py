"""Pruebas de integracion para el adaptador primario WebviewBridge y main.py.

Verifica que el puente sincrono expuesto a PyWebView delegue correctamente todas
las operaciones hacia el bucle `asyncio` en segundo plano y se comunique por UDP
real con `FakeWizBulbServer`, devolviendo diccionarios JSON serializables con el
estado actualizado de los focos y las 36 escenas nativas de WiZ.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.main import main as run_main


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

            # 8. La bandeja invierte el estado real, no la direccion cacheada.
            # El foco 1 se apaga por fuera (llave de pared o app WiZ) sin que la app lo sepa,
            # asi que el cache sigue diciendo "encendido": con esa direccion el item de la
            # bandeja habria apagado. `toggle_power` relee primero y enciende.
            server_one.pilot_state["state"] = False
            stale = await asyncio.to_thread(bridge.get_tray_snapshot)
            assert stale["is_on"] is True

            toggled = await asyncio.to_thread(bridge.toggle_power)
            assert toggled["ok"] is True
            assert server_one.pilot_state["state"] is True
            assert server_two.pilot_state["state"] is True

            # El segundo toggle ya parte del estado real encendido y apaga.
            turned_off = await asyncio.to_thread(bridge.toggle_power)
            assert turned_off["ok"] is True
            assert server_one.pilot_state["state"] is False
            assert server_two.pilot_state["state"] is False
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


async def test_webview_bridge_theme_and_fit_window_height(tmp_path) -> None:
    """Verifica `set_theme` y `fit_window_height` expuestos en `WebviewBridge`."""
    from wiz_console.adapters.storage.json_repositories import JsonSettingsRepository

    fit_calls: list[int] = []
    settings_repo = JsonSettingsRepository(data_dir=tmp_path)
    service = LightControlService(
        controller=WizUdpController(probe_candidates=[]),
        settings_repository=settings_repo,
    )
    bridge = WebviewBridge(
        service=service,
        fit_window_height=lambda px: fit_calls.append(px) or True,
    )
    try:
        initial = await asyncio.to_thread(bridge.get_initial_state)
        assert initial["ok"] is True
        assert initial["theme"] == "architectural-stone"

        dark_resp = await asyncio.to_thread(bridge.set_theme, "atmospheric-dark")
        assert dark_resp["ok"] is True
        assert dark_resp["theme"] == "atmospheric-dark"
        assert bridge.get_tray_snapshot()["theme"] == "atmospheric-dark"

        invalid_type_resp = await asyncio.to_thread(bridge.set_theme, 123)  # type: ignore[arg-type]
        assert invalid_type_resp["ok"] is False
        assert invalid_type_resp["error"] is not None

        assert bridge.fit_window_height(640) == {"ok": True}
        assert fit_calls == [640]
        assert bridge.fit_window_height(True)["ok"] is False  # type: ignore[arg-type]
        assert bridge.fit_window_height(100)["ok"] is False
        assert bridge.fit_window_height(5000)["ok"] is False
        assert fit_calls == [640]
    finally:
        bridge.shutdown()


async def test_tray_state_refresh_never_notifies_the_ui() -> None:
    """El sondeo de la bandeja lee el estado real sin avisar a la vista (S3)."""
    async with FakeWizBulbServer(mac="a8bb50998812") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(controller=controller)
        bridge = WebviewBridge(service=service)
        notifications: list[int] = []
        bridge.set_state_change_listener(lambda: notifications.append(1))

        try:
            initial = await asyncio.to_thread(bridge.get_initial_state)
            assert initial["ok"] is True
            notifications.clear()

            # El sondeo de la bandeja no es un cambio de estado: no notifica.
            tray_refresh = await asyncio.to_thread(bridge.refresh_tray_states)
            assert tray_refresh["ok"] is True
            assert notifications == []

            # El refresco que pide la vista si tiene que avisar.
            refresh = await asyncio.to_thread(bridge.refresh_states)
            assert refresh["ok"] is True
            assert notifications
        finally:
            bridge.shutdown()


async def test_bridge_call_survives_a_loop_thread_that_starts_late(monkeypatch) -> None:
    """Un hilo del bucle desalojado antes de entrar en `run_forever` no rompe el primer llamado.

    El puente arranca su bucle en un hilo demonio. En un runner de CI de dos nucleos, con los
    hilos de los tests previos todavia compitiendo, ese hilo puede quedar desalojado justo
    antes de entrar en `run_forever`: el bucle existe pero no corre. Si el puente se declara
    listo antes de que el bucle corra, el primer llamado desde PyWebView responde
    `{ok: False}` con "Background asyncio event loop is not running" aunque nada este roto.
    """
    real_run_forever = asyncio.BaseEventLoop.run_forever

    def slow_run_forever(self: asyncio.BaseEventLoop, *args: object, **kwargs: object) -> None:
        # Simula el desalojo del hilo del bucle con el bucle todavia sin correr.
        time.sleep(0.2)
        real_run_forever(self, *args, **kwargs)

    monkeypatch.setattr(asyncio.BaseEventLoop, "run_forever", slow_run_forever)

    async with FakeWizBulbServer(mac="a8bb50aa00bb") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        service = LightControlService(controller=controller)
        bridge = WebviewBridge(service=service)

        try:
            initial = await asyncio.to_thread(bridge.get_initial_state)
            assert initial["ok"] is True, initial.get("error")
            assert len(initial["bulbs"]) == 1
        finally:
            bridge.shutdown()


def test_bridge_rejects_non_finite_overflow_and_wrong_typed_js_inputs() -> None:
    """Reject NaN, Inf, OverflowError, booleans-as-int, and non-list/non-string arguments."""
    from unittest.mock import MagicMock

    service = LightControlService(controller=WizUdpController(probe_candidates=[]))
    autostart = MagicMock()
    bridge = WebviewBridge(service=service, autostart=autostart)
    try:
        invalid_calls = [
            bridge.set_brightness(True),  # type: ignore[arg-type]
            bridge.set_brightness(float("nan")),  # type: ignore[arg-type]
            bridge.set_brightness(float("inf")),  # type: ignore[arg-type]
            bridge.set_color(True, 0, 0),  # type: ignore[arg-type]
            bridge.set_temperature(float("nan")),  # type: ignore[arg-type]
            bridge.set_builtin_scene(1.5),  # type: ignore[arg-type]
            bridge.set_power(1),  # type: ignore[arg-type]
            bridge.select_targets("192.168.1.1"),  # type: ignore[arg-type]
            bridge.select_targets([123]),  # type: ignore[list-item]
            bridge.rename_bulb(123, "Lamp"),  # type: ignore[arg-type]
            bridge.start_ambilight(smoothing_alpha=float("nan")),
            bridge.start_music_sync(sensitivity=float("inf")),
            bridge.start_sleep_timer(float("nan")),
            bridge.start_sleep_timer(10**400),
            bridge.start_sleep_timer(True),  # type: ignore[arg-type]
            bridge.set_autostart("yes"),  # type: ignore[arg-type]
        ]
        for resp in invalid_calls:
            assert resp["ok"] is False
            assert isinstance(resp["error"], str) and resp["error"]
        autostart.enable.assert_not_called()
        autostart.disable.assert_not_called()
    finally:
        bridge.shutdown()


def test_bridge_sanitizes_internal_errors_from_js() -> None:
    """Internal OS, runtime, timeout, and native callback exceptions never leak paths or traces."""
    from unittest.mock import MagicMock

    from wiz_console.adapters.ui_webview.bridge import JsApi

    class FailingService(LightControlService):
        def __init__(self) -> None:
            super().__init__(controller=WizUdpController(probe_candidates=[]))
            self.exc: BaseException = OSError(r"C:\secret\bulbs.json")

        async def set_power(
            self,
            is_on: bool,
            brightness: int | None = None,
            ips: list[str] | None = None,
        ) -> list[Any]:
            raise self.exc

    service = FailingService()
    autostart = MagicMock()
    autostart.is_enabled.side_effect = OSError(r"HKCU\secret\key")
    autostart.enable.side_effect = OSError(r"HKCU\secret\key")
    bridge = WebviewBridge(service=service, autostart=autostart)
    try:
        for exc in (
            OSError(r"C:\secret\bulbs.json"),
            RuntimeError("internal secret stack state"),
            TimeoutError("secret socket timeout"),
            OverflowError("secret numeric overflow"),
        ):
            service.exc = exc
            resp = bridge.set_power(True)
            assert resp["ok"] is False
            assert "secret" not in resp["error"].lower()
            assert "c:\\" not in resp["error"].lower()

        get_auto = bridge.get_autostart()
        assert get_auto["ok"] is False
        assert "secret" not in get_auto["error"].lower()
        assert "hkcu" not in get_auto["error"].lower()

        set_auto = bridge.set_autostart(True)
        assert set_auto["ok"] is False
        assert "secret" not in set_auto["error"].lower()
        assert "hkcu" not in set_auto["error"].lower()
    finally:
        bridge.shutdown()

    api = JsApi(
        MagicMock(),
        fit_window=lambda _px: (_ for _ in ()).throw(RuntimeError(r"C:\secret\hwnd")),
    )
    fit_resp = api.fit_window_height(640)
    assert fit_resp["ok"] is False
    assert "secret" not in fit_resp["error"].lower()
    assert "c:\\" not in fit_resp["error"].lower()
