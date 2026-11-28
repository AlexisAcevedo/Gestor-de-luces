"""Regression tests for the security audit findings (M-1, M-2, B-1, B-2)."""

from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from wiz_console.adapters.storage.json_repositories import _atomic_write_json
from wiz_console.adapters.ui_webview.bridge import (
    JS_API_DISPATCH,
    JS_API_EXCLUDED,
    BlockedJsApi,
    JsApi,
    WebviewBridge,
    build_exposed_functions,
)
from wiz_console.adapters.ui_webview.lifecycle import ASYNC_LOOP_THREAD_NAME
from wiz_console.adapters.wiz import udp_controller as udp_controller_module
from wiz_console.adapters.wiz.udp_controller import WizUdpController, _safe_int, _safe_text
from wiz_console.application.service import (
    MAX_DISPLAY_NAME_LEN,
    MAX_EXPLICIT_TARGETS,
    LightControlService,
    validate_local_endpoint,
)
from wiz_console.domain.models import Bulb


@pytest.mark.parametrize("value", [float("inf"), "abc", None, [], {}])
def test_safe_int_never_raises_on_untrusted_values(value: object) -> None:
    assert _safe_int(value, 7) == 7


def test_safe_text_truncates_network_strings() -> None:
    assert len(_safe_text("A" * 60_000, "x")) == 64
    assert _safe_text(None, "fallback") == "fallback"


@pytest.mark.parametrize("dimming", [float("inf"), "abc", None])
async def test_get_state_survives_malformed_pilot(dimming: object) -> None:
    controller = WizUdpController()

    async def fake_send(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"result": {"state": True, "dimming": dimming, "r": "x", "g": 1, "b": 2}}

    controller._send_request = fake_send  # type: ignore[method-assign]
    state = await controller.get_state("192.168.1.10")
    assert state is not None
    assert 10 <= state.brightness <= 100


@pytest.mark.parametrize("value", ["192.168.1.5", "10.0.0.2", "127.0.0.1:38899", "169.254.1.1"])
def test_validate_local_endpoint_accepts_local_addresses(value: str) -> None:
    assert validate_local_endpoint(value) == value


@pytest.mark.parametrize(
    "value", ["8.8.8.8", "example.com", "192.168.1.5:0", "192.168.1.5:abc", "::1", ""]
)
def test_validate_local_endpoint_rejects_remote_or_malformed(value: str) -> None:
    with pytest.raises(ValueError):
        validate_local_endpoint(value)


def test_max_explicit_targets_is_bounded() -> None:
    assert 1 <= MAX_EXPLICIT_TARGETS <= 256


# El puente vive partido en varios modulos (T-4.4); los guardrails que lo inspeccionan
# por AST recorren todos para no perder superficie al mover un handler de archivo.
_BRIDGE_MODULES = ("bridge.py", "dispatch.py", "handlers.py", "lifecycle.py")


def _bridge_modules() -> list[Path]:
    """Rutas absolutas de los modulos que componen el puente IPC."""
    src_root = Path(__file__).resolve().parents[1] / "src" / "wiz_console"
    ui_root = src_root / "adapters" / "ui_webview"
    return [ui_root / name for name in _BRIDGE_MODULES]


_JS_API_SURFACE = frozenset(
    {
        "add_manual_bulb",
        "apply_custom_scene",
        "cancel_sleep_timer",
        "delete_custom_scene",
        "discover_bulbs",
        "fit_window_height",
        "get_ambilight_status",
        "get_autostart",
        "get_initial_state",
        "get_music_sync_status",
        "get_sleep_timer_status",
        "refresh_states",
        "remove_bulb",
        "rename_bulb",
        "save_custom_scene",
        "select_targets",
        "set_autostart",
        "set_brightness",
        "set_builtin_scene",
        "set_color",
        "set_custom_scene_favorite",
        "set_language",
        "set_power",
        "set_temperature",
        "set_theme",
        "start_ambilight",
        "start_music_sync",
        "start_sleep_timer",
        "stop_ambilight",
        "stop_music_sync",
        "update_custom_scene",
    }
)


def test_js_api_dispatch_table_is_explicit_and_pinned() -> None:
    """La superficie JS vive en una tabla escrita a mano, no en reflexion sobre la clase."""
    assert set(JS_API_DISPATCH) == _JS_API_SURFACE - {"fit_window_height"}
    for name, handler in JS_API_DISPATCH.items():
        assert name in _JS_API_SURFACE
        assert handler is getattr(WebviewBridge, name)


def test_js_api_hides_lifecycle_methods() -> None:
    """Ni la tabla ni la instancia exponen los metodos de ciclo de vida o de bandeja."""
    assert not set(JS_API_DISPATCH) & JS_API_EXCLUDED
    api = JsApi(MagicMock())
    public = {n for n in dir(api) if not n.startswith("_")}
    assert public == _JS_API_SURFACE
    assert not public & JS_API_EXCLUDED
    assert "set_power" in public


def test_js_api_binds_every_exposed_method_to_the_bridge_instance() -> None:
    """Cada nombre JS sigue siendo el metodo del puente ligado a esa instancia."""
    bridge = MagicMock()
    api = JsApi(bridge)
    for name in JS_API_DISPATCH:
        assert getattr(api, name).__self__ is bridge


def test_blocked_js_api_blocks_all_getattr_and_dir_traversal() -> None:
    """`BlockedJsApi` oculta todo atributo para impedir traversal por puntos en pywebview."""
    blocked = BlockedJsApi()
    assert dir(blocked) == []
    for attr in ("_bridge", "_fit_window", "__class__", "__dict__", "__mro__", "set_power"):
        assert getattr(blocked, attr, None) is None


def test_window_expose_registers_only_allowlisted_functions_and_blocks_traversal() -> None:
    """`Window.expose` publica solo los 30 callables planos y bloquea traversal via `js_api`."""
    import inspect

    import webview.util
    import webview.window

    bridge = MagicMock()
    bridge._call.return_value = {"ok": True}
    api = JsApi(bridge, fit_window=lambda _px: True)
    window = webview.window.Window(
        uid="test-sec",
        title="Security Test",
        url=None,
        js_api=BlockedJsApi(),
    )
    window.expose(*build_exposed_functions(api))

    assert set(window._functions) == _JS_API_SURFACE
    for name, fn in window._functions.items():
        assert inspect.getfullargspec(fn).args == [], f"{name} leaked signature parameters"

    assert window._functions["set_power"](True, 50) == {"ok": True}
    bridge._call.assert_called_once()
    assert window._functions["fit_window_height"](600) == {"ok": True}

    eval_calls: list[str] = []
    window.evaluate_js = lambda script: eval_calls.append(script)  # type: ignore[method-assign]
    for dangerous in (
        "_bridge.shutdown",
        "_bridge._service",
        "__class__.__base__.__subclasses__",
        "set_power.__closure__",
        "shutdown",
        "get_tray_snapshot",
    ):
        webview.util.js_bridge_call(window, dangerous, [], "req-1")

    bridge.shutdown.assert_not_called()
    assert eval_calls == []


def test_bridge_narrows_service_errors_to_the_declared_tuple() -> None:
    """Un error esperado del servicio sigue devolviendo `{ok: False, error}`."""

    class ValidationService(LightControlService):
        async def set_power(
            self,
            is_on: bool,
            brightness: int | None = None,
            ips: list[str] | None = None,
        ) -> list[Bulb]:
            raise ValueError("Brightness must be between 10 and 100.")

    bridge = WebviewBridge(
        service=ValidationService(controller=WizUdpController(probe_candidates=[]))
    )
    try:
        response = bridge.set_power(True)
    finally:
        bridge.shutdown()
    assert response["ok"] is False
    assert response["error"] == "Brightness must be between 10 and 100."


def test_bridge_propagates_errors_outside_the_declared_tuple() -> None:
    """Un error inesperado ya no se silencia: sale del puente en vez de fingir un fallo de UI."""

    class UnexpectedError(Exception):
        pass

    class ExplodingService(LightControlService):
        async def set_power(
            self,
            is_on: bool,
            brightness: int | None = None,
            ips: list[str] | None = None,
        ) -> list[Bulb]:
            raise UnexpectedError("boom")

    bridge = WebviewBridge(
        service=ExplodingService(controller=WizUdpController(probe_candidates=[]))
    )
    try:
        with pytest.raises(UnexpectedError):
            bridge.set_power(True)
    finally:
        bridge.shutdown()


async def test_discover_ignores_broadcast_hits_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WizUdpController()

    async def fake_discover_lights(*_a: object, **_kw: object) -> list[object]:
        return [SimpleNamespace(ip="192.168.1.99", mac="aabbccddeeff")]

    async def fake_probe(ip: str, timeout: float = 1.0) -> Bulb | None:
        return None

    monkeypatch.setattr("wiz_console.adapters.wiz.udp_controller.detect_local_ipv4", lambda: None)
    monkeypatch.setattr(
        "wiz_console.adapters.wiz.udp_controller.discovery.discover_lights",
        fake_discover_lights,
    )
    monkeypatch.setattr(controller, "probe_bulb", fake_probe)

    assert await controller.discover(wait_time=0.05) == []


async def test_display_name_length_is_bounded() -> None:
    controller = WizUdpController(probe_candidates=[])

    async def fake_probe(ip: str, timeout: float = 1.0) -> Bulb | None:
        return Bulb(ip=ip)

    controller.probe_bulb = fake_probe  # type: ignore[method-assign]
    service = LightControlService(controller=controller)
    await service.add_manual_bulb("192.168.1.20", name="Valid")

    too_long = "X" * (MAX_DISPLAY_NAME_LEN + 1)
    with pytest.raises(ValueError):
        service.rename_bulb("192.168.1.20", too_long)
    with pytest.raises(ValueError):
        service.save_custom_scene_from_current(too_long)


def test_atomic_write_json_cleans_up_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "bulbs.json"
    _atomic_write_json(target, [{"ip": "192.168.1.10"}])
    assert target.is_file()
    leftovers = [p for p in tmp_path.iterdir() if p != target]
    assert leftovers == []


async def test_stream_pilot_reuses_udp_socket_and_closes_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El flujo continuo abre UN solo socket UDP y `close()` lo libera.

    Se observa el socket mismo (cuantos se crean y si queda con descriptor), no un atributo
    privado del controlador: el contrato es «no filtrar sockets», y eso se mide en el objeto
    que el sistema operativo entrega.
    """
    from wiz_console.domain.value_objects import Color

    created: list[socket.socket] = []
    real_socket = socket.socket

    def _counting_socket(*args: object, **kwargs: object) -> socket.socket:
        sock = real_socket(*args, **kwargs)  # type: ignore[arg-type]
        created.append(sock)
        return sock

    class _SocketModuleShim:
        """Reemplaza solo el nombre `socket` del modulo; el modulo real queda intacto."""

        socket = staticmethod(_counting_socket)

        def __getattr__(self, name: str) -> object:
            return getattr(socket, name)

    # Se sustituye el nombre en el modulo del adaptador, no el modulo `socket` global: parchear
    # el global rompe el bucle Proactor de asyncio, que hace `isinstance(conn, socket.socket)`.
    monkeypatch.setattr(udp_controller_module, "socket", _SocketModuleShim())

    controller = WizUdpController(port=49999)
    try:
        await controller.stream_pilot("127.0.0.1", Color(255, 100, 50), 80)
        await controller.stream_pilot("127.0.0.1", Color(10, 200, 90), 60)
        assert len(created) == 1, "the continuous stream opened more than one UDP socket"
        stream_sock = created[0]
        assert stream_sock.fileno() >= 0
    finally:
        controller.close()
    assert stream_sock.fileno() == -1, "close() left the streaming socket open"


def test_inner_hexagonal_layers_never_import_adapters() -> None:
    import ast

    src_root = Path(__file__).resolve().parents[1] / "src" / "wiz_console"
    for layer in ("domain", "ports", "application"):
        for py_file in (src_root / layer).rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("wiz_console.adapters"), (
                            f"{py_file} imports {alias.name}"
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("wiz_console.adapters"), (
                        f"{py_file} imports from {node.module}"
                    )


def test_webview_bridge_depends_on_the_port_not_the_concrete_service() -> None:
    """El adaptador primario depende del puerto, nunca de la clase de aplicacion (T-4.3)."""
    import ast

    for bridge_file in _bridge_modules():
        tree = ast.parse(bridge_file.read_text(encoding="utf-8"), filename=str(bridge_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("wiz_console.application"), (
                        f"{bridge_file} imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("wiz_console.application"), (
                    f"{bridge_file} imports from {node.module}"
                )
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert alias.name != "LightControlService", (
                        f"{bridge_file} imports the concrete LightControlService"
                    )


def test_light_control_port_covers_the_service_surface_the_bridge_uses() -> None:
    """El puerto declara justo lo que el puente consume, y el servicio lo satisface."""
    import ast
    import inspect
    from typing import get_origin, get_type_hints

    from wiz_console.ports.light_control import LightControlServicePort

    def satisfies(port_return: object, service_return: object) -> bool:
        """`service_return` cumple `port_return` si es el mismo o un subtipo estructural."""
        if port_return == service_return:
            return True
        origin = get_origin(port_return) or port_return
        return (
            isinstance(service_return, type)
            and isinstance(origin, type)
            and issubclass(service_return, origin)
        )

    consumed = {
        node.func.attr
        for bridge_file in _bridge_modules()
        for node in ast.walk(
            ast.parse(bridge_file.read_text(encoding="utf-8"), filename=str(bridge_file))
        )
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_service"
    }
    declared = {name for name in vars(LightControlServicePort) if not name.startswith("_")}
    assert consumed == declared

    for name in sorted(declared):
        port_params = inspect.signature(getattr(LightControlServicePort, name)).parameters
        service_params = list(
            inspect.signature(getattr(LightControlService, name)).parameters.values()
        )[: len(port_params)]
        assert list(port_params) == [param.name for param in service_params]
        assert [param.default for param in port_params.values()] == [
            param.default for param in service_params
        ]
        port_return = get_type_hints(getattr(LightControlServicePort, name))["return"]
        service_return = get_type_hints(getattr(LightControlService, name))["return"]
        assert satisfies(port_return, service_return), (
            f"{name}: {service_return} does not satisfy {port_return}"
        )


def test_webview_bridge_build_response_marshals_reads_onto_event_loop() -> None:
    import threading

    controller = WizUdpController(probe_candidates=[])
    observed_threads: list[str] = []

    class TrackingService(LightControlService):
        def list_bulbs(self) -> list[Bulb]:
            observed_threads.append(threading.current_thread().name)
            return super().list_bulbs()

    service = TrackingService(controller=controller)
    bridge = WebviewBridge(service=service)
    try:
        resp = bridge.get_sleep_timer_status()
        assert resp["ok"] is True
        assert ASYNC_LOOP_THREAD_NAME in observed_threads
    finally:
        bridge.shutdown()


def test_index_html_has_no_inline_style_attributes() -> None:
    import re

    from wiz_console.main import resolve_ui_directory

    index_html = (resolve_ui_directory() / "index.html").read_text(encoding="utf-8")
    assert re.search(r"\bstyle\s*=", index_html, flags=re.IGNORECASE) is None
