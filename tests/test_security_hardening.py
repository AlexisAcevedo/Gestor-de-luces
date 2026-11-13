"""Regression tests for the security audit findings (M-1, M-2, B-1, B-2)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gestor_luces.adapters.storage.json_repositories import _atomic_write_json
from gestor_luces.adapters.ui_webview.bridge import (
    JS_API_DISPATCH,
    JS_API_EXCLUDED,
    JsApi,
    WebviewBridge,
)
from gestor_luces.adapters.wiz.udp_controller import WizUdpController, _safe_int, _safe_text
from gestor_luces.application.service import (
    MAX_DISPLAY_NAME_LEN,
    MAX_EXPLICIT_TARGETS,
    LightControlService,
    validate_local_endpoint,
)
from gestor_luces.domain.models import Bulb


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
    assert api._bridge is bridge


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

    monkeypatch.setattr("gestor_luces.adapters.wiz.udp_controller.detect_local_ipv4", lambda: None)
    monkeypatch.setattr(
        "gestor_luces.adapters.wiz.udp_controller.discovery.discover_lights",
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


async def test_stream_pilot_reuses_udp_socket_and_closes_cleanly() -> None:
    from gestor_luces.domain.value_objects import Color

    controller = WizUdpController(port=49999)
    await controller.stream_pilot("127.0.0.1", Color(255, 100, 50), 80)
    first_sock = controller._stream_sock
    assert first_sock is not None and first_sock.fileno() >= 0

    await controller.stream_pilot("127.0.0.1", Color(10, 200, 90), 60)
    assert controller._stream_sock is first_sock

    controller.close()
    assert controller._stream_sock is None


def test_inner_hexagonal_layers_never_import_adapters() -> None:
    import ast

    src_root = Path(__file__).resolve().parents[1] / "src" / "gestor_luces"
    for layer in ("domain", "ports", "application"):
        for py_file in (src_root / layer).rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("gestor_luces.adapters"), (
                            f"{py_file} imports {alias.name}"
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("gestor_luces.adapters"), (
                        f"{py_file} imports from {node.module}"
                    )


def test_webview_bridge_depends_on_the_port_not_the_concrete_service() -> None:
    """El adaptador primario depende del puerto, nunca de la clase de aplicacion (T-4.3)."""
    import ast

    src_root = Path(__file__).resolve().parents[1] / "src" / "gestor_luces"
    bridge_file = src_root / "adapters" / "ui_webview" / "bridge.py"
    tree = ast.parse(bridge_file.read_text(encoding="utf-8"), filename=str(bridge_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("gestor_luces.application"), (
                    f"{bridge_file} imports {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("gestor_luces.application"), (
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

    from gestor_luces.ports.light_control import LightControlServicePort

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

    src_root = Path(__file__).resolve().parents[1] / "src" / "gestor_luces"
    bridge_file = src_root / "adapters" / "ui_webview" / "bridge.py"
    tree = ast.parse(bridge_file.read_text(encoding="utf-8"), filename=str(bridge_file))
    consumed = {
        node.func.attr
        for node in ast.walk(tree)
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
        assert "GestorLucesAsyncLoop" in observed_threads
    finally:
        bridge.shutdown()


def test_index_html_has_no_inline_style_attributes() -> None:
    import re

    from gestor_luces.main import resolve_ui_directory

    index_html = (resolve_ui_directory() / "index.html").read_text(encoding="utf-8")
    assert re.search(r"\bstyle\s*=", index_html, flags=re.IGNORECASE) is None
