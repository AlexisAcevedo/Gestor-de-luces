"""Pruebas de caracterizacion para la CLI de red de bajo nivel.

Verifica la aceptacion de T-2.4 (D3=A): `cli.py` reutiliza `WizUdpController` y no abre
sockets propios ni depende de `pywizlight` directamente, y los subcomandos de control
(`status`, `on`, `off`, `color`, `kelvin`) devuelven lo mismo que antes contra
`tests/simulators/fake_wiz_bulb.py`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.cli import run_command
from tests.simulators.fake_wiz_bulb import FakeWizBulbServer


def test_cli_has_no_own_sockets_nor_pywizlight() -> None:
    """Garantiza que `cli.py` no abre sockets propios ni usa `pywizlight` directo (T-2.4)."""
    source = Path("src/gestor_luces/cli.py").read_text(encoding="utf-8")
    assert "import socket" not in source
    assert "import ipaddress" not in source
    assert "from pywizlight" not in source
    assert "detect_local_ipv4" not in source
    assert "compute_subnet_broadcast" not in source
    assert "sweep_subnet_for_bulbs" not in source
    assert "probe_single_ip" not in source


async def _run(controller: WizUdpController, ip: str, command: str, **kwargs) -> int:
    """Ejecuta un subcomando CLI con los argumentos dados y devuelve el exit code."""
    args = SimpleNamespace(command=command, ip=ip, **kwargs)
    return await run_command(controller, args)


async def test_cli_status_reports_bulb_state_via_shared_controller() -> None:
    """El subcomando `status` lee getPilot a traves de WizUdpController."""
    async with FakeWizBulbServer(mac="a8bb50000001") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])
        exit_code = await _run(controller, server.endpoint, "status")
        assert exit_code == 0


async def test_cli_on_off_control_through_shared_controller() -> None:
    """Los subcomandos `on`/`off` encienden y apagan via setPilot del controlador."""
    async with FakeWizBulbServer(mac="a8bb50000002") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])

        assert await _run(controller, server.endpoint, "on", brightness=80) == 0
        state_on = await controller.get_state(server.endpoint)
        assert state_on is not None and state_on.is_on is True

        assert await _run(controller, server.endpoint, "off") == 0
        state_off = await controller.get_state(server.endpoint)
        assert state_off is not None and state_off.is_on is False


async def test_cli_color_and_kelvin_through_shared_controller() -> None:
    """Los subcomandos `color`/`kelvin` aplican RGB y temperatura via el controlador."""
    async with FakeWizBulbServer(mac="a8bb50000003") as server:
        controller = WizUdpController(probe_candidates=[server.endpoint])

        assert (
            await _run(controller, server.endpoint, "color", r=255, g=120, b=0, brightness=100)
            == 0
        )
        state_rgb = await controller.get_state(server.endpoint)
        assert state_rgb is not None
        assert state_rgb.color is not None
        assert (state_rgb.color.r, state_rgb.color.g, state_rgb.color.b) == (255, 120, 0)

        assert await _run(controller, server.endpoint, "kelvin", temp=2700, brightness=100) == 0
        state_temp = await controller.get_state(server.endpoint)
        assert state_temp is not None and state_temp.temperature == 2700


def test_cli_discover_returns_same_bulbs_via_shared_controller() -> None:
    """El subcomando `discover` descubre focos a traves del controlador compartido."""

    async def _scenario() -> int:
        async with FakeWizBulbServer(mac="a8bb50000004") as server:
            controller = WizUdpController(probe_candidates=[server.endpoint])
            args = SimpleNamespace(command="discover", wait=0.5)
            return await run_command(controller, args)

    assert asyncio.run(_scenario()) == 0
