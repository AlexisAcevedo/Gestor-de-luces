"""Tests for opt-in loopback Local HTTP API authentication, size caps, and routes (PR 3.3)."""

from __future__ import annotations

import asyncio
import http.client
import json
import secrets
from pathlib import Path
from typing import Any

import pytest

from tests.simulators.fake_wiz_bulb import FakeWizBulbServer
from wiz_console.adapters.api.local_http_api import LocalHttpApiServer
from wiz_console.adapters.storage.json_repositories import JsonSettingsRepository
from wiz_console.adapters.ui_webview.bridge import WebviewBridge
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.domain.automation import LocalApiConfig


def _http_call(
    port: int,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | str | None = None,
) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3.0)
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    raw_body: bytes | None = None
    if isinstance(body, dict):
        raw_body = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif isinstance(body, str):
        raw_body = body.encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=raw_body, headers=headers)
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        return resp.status, payload
    finally:
        conn.close()


def test_local_api_config_validation_and_token_rotation(tmp_path: Path) -> None:
    """Config rejects invalid ports, auto-generates tokens when enabled, and rotates."""
    with pytest.raises(ValueError):
        LocalApiConfig(port=80)
    settings_repo = JsonSettingsRepository(tmp_path / "settings.json")
    service = LightControlService(controller=WizUdpController(), settings_repository=settings_repo)

    enabled = service.set_local_api_config({"enabled": True, "port": 18999})
    assert enabled["enabled"] is True
    assert enabled["port"] == 18999
    first_token = enabled["token"]
    assert len(first_token) >= 24

    rotated = service.rotate_local_api_token()
    assert rotated["token"] != first_token
    assert settings_repo.load_settings()["local_api"]["token"] == rotated["token"]


async def test_local_http_api_auth_body_limit_and_routes(tmp_path: Path) -> None:
    """Loopback HTTP server enforces Bearer auth, 16 KiB limit, and dispatches light routes."""
    async with FakeWizBulbServer(mac="a8bb50dd1122") as bulb_server:
        controller = WizUdpController(probe_candidates=[bulb_server.endpoint])
        settings_repo = JsonSettingsRepository(tmp_path / "settings.json")
        service = LightControlService(controller=controller, settings_repository=settings_repo)
        await service.discover_bulbs()

        bridge = WebviewBridge(service=service)
        api_server = LocalHttpApiServer(bridge)
        token = secrets.token_urlsafe(16)
        wrong_token = secrets.token_urlsafe(12)
        port = api_server.start(port=0, token=token)
        try:
            # Unauthorized & wrong token must return 401
            status_unauth, _ = await asyncio.to_thread(_http_call, port, "GET", "/api/v1/status")
            assert status_unauth == 401
            status_wrong, _ = await asyncio.to_thread(
                _http_call, port, "GET", "/api/v1/status", token=wrong_token
            )
            assert status_wrong == 401

            # Oversized body (> 16 KiB) rejected with 413
            oversized = json.dumps({"pad": "x" * 17000})
            status_big, _ = await asyncio.to_thread(
                _http_call, port, "POST", "/api/v1/power", token=token, body=oversized
            )
            assert status_big == 413

            # Valid GET status does not leak local_api token
            status_ok, status_data = await asyncio.to_thread(
                _http_call, port, "GET", "/api/v1/status", token=token
            )
            assert status_ok == 200
            assert "local_api" not in status_data
            assert len(status_data["bulbs"]) == 1

            # Valid POST color + temperature + brightness
            st_color, _ = await asyncio.to_thread(
                _http_call,
                port,
                "POST",
                "/api/v1/color",
                token=token,
                body={"r": 12, "g": 34, "b": 56, "brightness": 88},
            )
            assert st_color == 200
            assert (
                bulb_server.pilot_state["r"],
                bulb_server.pilot_state["g"],
                bulb_server.pilot_state["b"],
            ) == (
                12,
                34,
                56,
            )

            st_temp, _ = await asyncio.to_thread(
                _http_call,
                port,
                "POST",
                "/api/v1/temperature",
                token=token,
                body={"kelvin": 5100, "brightness": 72},
            )
            assert st_temp == 200
            assert bulb_server.pilot_state["temp"] == 5100
        finally:
            api_server.stop()
            bridge.shutdown()
