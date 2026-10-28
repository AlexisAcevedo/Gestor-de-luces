"""Regression tests for the security audit findings (M-1, M-2, B-1, B-2)."""

from __future__ import annotations

import pytest

from gestor_luces.adapters.storage.json_repositories import _atomic_write_json
from gestor_luces.adapters.ui_webview.bridge import JS_API_EXCLUDED, JsApi, WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController, _safe_int, _safe_text
from gestor_luces.application.service import (
    MAX_DISPLAY_NAME_LEN,
    MAX_EXPLICIT_TARGETS,
    LightControlService,
    validate_local_endpoint,
)
from gestor_luces.domain.models import Bulb
from pathlib import Path
from types import SimpleNamespace


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


def test_js_api_hides_lifecycle_methods() -> None:
    api = JsApi.__new__(JsApi)
    for name in dir(WebviewBridge):
        if not name.startswith("_") and name not in JS_API_EXCLUDED:
            setattr(api, name, lambda: None)
    public = {n for n in dir(api) if not n.startswith("_")}
    assert not public & JS_API_EXCLUDED
    assert "set_power" in public


async def test_discover_ignores_broadcast_hits_when_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
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



