"""Simulador UDP local de un foco inteligente Philips WiZ A60.

Permite verificar el adaptador WizUdpController y el servicio LightControlService
de punta a punta sobre sockets UDP reales en 127.0.0.1 usando puertos efimeros
asignados por el sistema operativo, sin depender de un foco fisico en la red.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class _FakeBulbProtocol(asyncio.DatagramProtocol):
    """Protocolo UDP que procesa los comandos JSON del protocolo WiZ."""

    def __init__(self, server: FakeWizBulbServer) -> None:
        self._server = server
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            return

        response = self._server.handle_message(payload)
        if response is not None and self._transport is not None:
            encoded = json.dumps(response).encode("utf-8")
            self._transport.sendto(encoded, addr)


class FakeWizBulbServer:
    """Servidor UDP asincrono que emula el firmware de un foco WiZ en localhost."""

    def __init__(
        self,
        mac: str = "a8bb50000001",
        module_name: str = "ESP01_SHRGB1C_31",
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.mac = mac
        self.module_name = module_name
        self.host = host
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        self.received_messages: list[dict[str, Any]] = []

        # Estado interno equivalente al registro pilot del firmware real
        self.pilot_state: dict[str, Any] = {
            "mac": self.mac,
            "state": False,
            "dimming": 100,
            "temp": 4200,
            "sceneId": 0,
            "speed": 100,
        }

    @property
    def endpoint(self) -> str:
        """Devuelve la direccion 'host:puerto' en la que escucha el simulador."""
        return f"{self.host}:{self.port}"

    async def start(self) -> FakeWizBulbServer:
        """Inicia la escucha UDP en el puerto configurado (o uno efimero si es 0)."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _FakeBulbProtocol(self),
            local_addr=(self.host, self.port),
        )
        self._transport = transport
        sockname = transport.get_extra_info("sockname")
        if sockname:
            self.host = str(sockname[0])
            self.port = int(sockname[1])
        return self

    def close(self) -> None:
        """Cierra el socket UDP del simulador."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def __aenter__(self) -> FakeWizBulbServer:
        return await self.start()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def handle_message(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Procesa un mensaje JSON WiZ entrante y devuelve el diccionario de respuesta."""
        self.received_messages.append(payload)
        method = payload.get("method")
        params = payload.get("params") or {}

        if method == "getSystemConfig":
            return {
                "method": "getSystemConfig",
                "env": "pro",
                "result": {
                    "mac": self.mac,
                    "moduleName": self.module_name,
                    "fwVersion": "1.31.0",
                },
            }

        if method == "registration":
            return {
                "method": "registration",
                "env": "pro",
                "result": {
                    "mac": self.mac,
                    "success": True,
                },
            }

        if method == "getPilot":
            return {
                "method": "getPilot",
                "env": "pro",
                "result": dict(self.pilot_state),
            }

        if method == "setPilot":
            self._apply_set_pilot(params)
            return {
                "method": "setPilot",
                "env": "pro",
                "result": {"success": True},
            }

        return None

    def _apply_set_pilot(self, params: dict[str, Any]) -> None:
        """Actualiza el estado interno del foco simulado imitando las reglas del firmware."""
        if "state" in params:
            self.pilot_state["state"] = bool(params["state"])
        if "dimming" in params:
            self.pilot_state["dimming"] = int(params["dimming"])

        if all(k in params for k in ("r", "g", "b")):
            self.pilot_state["r"] = int(params["r"])
            self.pilot_state["g"] = int(params["g"])
            self.pilot_state["b"] = int(params["b"])
            self.pilot_state.pop("temp", None)
            self.pilot_state["sceneId"] = 0
        elif "temp" in params:
            self.pilot_state["temp"] = int(params["temp"])
            self.pilot_state.pop("r", None)
            self.pilot_state.pop("g", None)
            self.pilot_state.pop("b", None)
            self.pilot_state["sceneId"] = 0
        elif "sceneId" in params:
            self.pilot_state["sceneId"] = int(params["sceneId"])
            self.pilot_state.pop("r", None)
            self.pilot_state.pop("g", None)
            self.pilot_state.pop("b", None)
            self.pilot_state.pop("temp", None)
            if "speed" in params:
                self.pilot_state["speed"] = int(params["speed"])
