"""Security regression tests for endpoint validation, CLI, UDP controller, and JSON storage."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wiz_console.adapters.storage import json_repositories
from wiz_console.adapters.storage.json_repositories import (
    DEFAULT_SETTINGS,
    JsonBulbRepository,
    JsonSceneRepository,
    JsonSettingsRepository,
    _atomic_write_json,
)
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service_context import ServiceContext
from wiz_console.cli import build_parser, run_command
from wiz_console.domain import Bulb, Color, validate_local_endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "192.168.1.5",
        "192.168.1.5:38899",
        "10.0.0.2",
        "172.16.0.5",
        "169.254.1.1",
        "127.0.0.1",
        "127.0.0.1:38899",
        "127.0.0.1:54321",
    ],
)
def test_validate_local_endpoint_accepts_valid_local_unicast_endpoints(endpoint: str) -> None:
    assert validate_local_endpoint(endpoint) == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "0.0.0.0",  # noqa: S104
        "255.255.255.255",
        "224.0.0.1",
        "192.168.1.255",
        "10.0.0.0",
        "10.255.255.255",
        "172.16.0.0",
        "172.31.255.255",
        "192.168.0.0",
        "192.168.255.255",
        "169.254.0.1",
        "169.254.255.1",
        "192.0.2.1",
        "100.64.0.1",
        "8.8.8.8",
        "192.168.1.5:53",
        "192.168.1.5:80",
        "192.168.1.5:9999",
        "127.0.0.1:53",
        "127.0.0.1:1023",
        "127.0.0.1:²",
        "",
        "   ",
        123,
    ],
)
def test_validate_local_endpoint_rejects_unsafe_hosts_and_ports(endpoint: object) -> None:
    with pytest.raises(ValueError):
        validate_local_endpoint(endpoint)  # type: ignore[arg-type]


async def test_udp_controller_enforces_endpoint_validation() -> None:
    controller = WizUdpController()
    for bad in ("0.0.0.0", "255.255.255.255", "8.8.8.8", "192.168.1.5:53"):  # noqa: S104
        with pytest.raises(ValueError):
            await controller.probe_bulb(bad)
        with pytest.raises(ValueError):
            await controller.stream_pilot(bad, Color(255, 0, 0), 80)

    bad_port_ctrl = WizUdpController(port=53)
    with pytest.raises(ValueError):
        await bad_port_ctrl.probe_bulb("192.168.1.10")
    with pytest.raises(ValueError):
        await bad_port_ctrl.probe_bulb("127.0.0.1")


async def test_udp_controller_handles_create_datagram_endpoint_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WizUdpController()
    loop = asyncio.get_running_loop()

    async def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("network unreachable")

    monkeypatch.setattr(loop, "create_datagram_endpoint", boom)
    assert await controller.get_state("192.168.1.10") is None


async def test_udp_controller_get_state_guards_bool_scene_id_and_clamps_speed() -> None:
    controller = WizUdpController()

    async def fake_send(*_args: object, **_kwargs: object) -> dict[str, Any]:
        return {
            "result": {
                "state": True,
                "dimming": 80,
                "temp": 3000,
                "sceneId": True,
                "speed": 999,
            }
        }

    controller._send_request = fake_send  # type: ignore[method-assign]
    state = await controller.get_state("192.168.1.10")
    assert state is not None
    assert state.scene_id is None
    assert state.speed == 200


@pytest.mark.parametrize(
    "argv",
    [
        ["status", "--ip", "0.0.0.0"],  # noqa: S104
        ["status", "--ip", "8.8.8.8"],
        ["status", "--ip", "192.168.1.5:53"],
        ["discover", "--wait", "nan"],
        ["discover", "--wait", "-1"],
        ["discover", "--wait", "999"],
    ],
)
def test_cli_parser_rejects_unsafe_ips_and_invalid_wait(argv: list[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(argv)


async def test_cli_run_command_rejects_unsafe_ip_programmatically() -> None:
    controller = WizUdpController(probe_candidates=[])
    args = SimpleNamespace(command="status", ip="8.8.8.8")
    assert await run_command(controller, args) == 1


def test_json_repositories_handle_deep_recursion_and_create_corrupt_backup(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    nested = "[" * 25_000 + "]" * 25_000
    bulb_repo = JsonBulbRepository(data_dir=tmp_path)
    bulb_repo.file_path.write_text(nested, encoding="utf-8")

    settings_repo = JsonSettingsRepository(data_dir=tmp_path)
    settings_repo.file_path.write_text(
        '{"a": ' * 25_000 + "1" + "}" * 25_000,
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        assert bulb_repo.load_bulbs() == []
        assert settings_repo.load_settings() == DEFAULT_SETTINGS

    assert (tmp_path / "bulbs.json.corrupt").is_file()
    assert (tmp_path / "settings.json.corrupt").is_file()
    assert "Corrupt JSON file" in caplog.text


def test_json_repositories_enforce_file_size_and_record_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bulb_repo = JsonBulbRepository(data_dir=tmp_path)
    scene_repo = JsonSceneRepository(data_dir=tmp_path)

    bulb_payload = [{"ip": f"192.168.1.{i}"} for i in range(1, 6)]
    bulb_repo.file_path.write_text(json.dumps(bulb_payload), encoding="utf-8")

    scene_payload = [
        {"id": f"s{i}", "name": f"Scene {i}", "mode": "temperature", "temperature": 3000}
        for i in range(5)
    ]
    scene_repo.file_path.write_text(json.dumps(scene_payload), encoding="utf-8")

    monkeypatch.setattr(json_repositories, "MAX_BULB_RECORDS", 2)
    monkeypatch.setattr(json_repositories, "MAX_SCENE_RECORDS", 3)
    with caplog.at_level(logging.WARNING):
        assert len(bulb_repo.load_bulbs()) == 2
        assert len(scene_repo.load_scenes()) == 3

    monkeypatch.setattr(json_repositories, "MAX_JSON_FILE_BYTES", 10)
    assert bulb_repo.load_bulbs() == []


def test_json_bulb_repository_and_service_context_filter_unsafe_persisted_ips(
    tmp_path: Path,
) -> None:
    bulb_repo = JsonBulbRepository(data_dir=tmp_path)
    bulb_repo.file_path.write_text(
        json.dumps(
            [
                {"ip": "8.8.8.8"},
                {"ip": "0.0.0.0"},  # noqa: S104
                {"ip": "192.168.1.5:53"},
                {"ip": 123},
                {"ip": "192.168.1.20", "state": {"brightness": float("nan")}},
                {"ip": "192.168.1.21", "name": "Desk"},
            ]
        ),
        encoding="utf-8",
    )
    loaded = bulb_repo.load_bulbs()
    assert [b.ip for b in loaded] == ["192.168.1.21"]

    class TamperedRepo:
        def load_bulbs(self) -> list[Bulb]:
            bulb = Bulb(ip="192.168.1.30")
            bulb.ip = "8.8.8.8"
            return [bulb, Bulb(ip="192.168.1.31")]

        def save_bulbs(self, bulbs: list[Bulb]) -> None:
            return None

    ctx = ServiceContext(
        controller=WizUdpController(probe_candidates=[]),
        bulb_repository=TamperedRepo(),
    )
    assert [b.ip for b in ctx.list_bulbs()] == ["192.168.1.31"]


def test_atomic_write_json_retries_permission_error_and_cleans_up_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "bulbs.json"
    attempts = {"count": 0}
    real_replace = json_repositories.os.replace

    def flaky_replace(src: Path, dst: Path) -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("file locked by antivirus")
        real_replace(src, dst)

    monkeypatch.setattr(json_repositories.time, "sleep", lambda _s: None)
    monkeypatch.setattr(json_repositories.os, "replace", flaky_replace)

    _atomic_write_json(target, [{"ip": "192.168.1.10"}])
    assert attempts["count"] == 3
    assert target.is_file()

    def always_locked(_src: Path, _dst: Path) -> None:
        raise PermissionError("locked permanently")

    monkeypatch.setattr(json_repositories.os, "replace", always_locked)
    with pytest.raises(PermissionError):
        _atomic_write_json(target, [{"ip": "192.168.1.11"}])
    assert [p for p in tmp_path.iterdir() if p != target] == []
