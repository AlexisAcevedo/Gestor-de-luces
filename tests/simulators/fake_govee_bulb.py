"""Local UDP simulator for a Govee LAN smart light (devStatus, turn, brightness, colorwc)."""

from __future__ import annotations

import asyncio
import json
from typing import Any


class _FakeGoveeProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: FakeGoveeBulbServer) -> None:
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
            self._transport.sendto(json.dumps(response).encode("utf-8"), addr)


class FakeGoveeBulbServer:
    """Async UDP server emulating the Govee LAN control JSON protocol on localhost."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        self.state: dict[str, Any] = {
            "onOff": 0,
            "brightness": 80,
            "color": {"r": 255, "g": 200, "b": 150},
            "colorTemInKelvin": 0,
        }

    @property
    def endpoint(self) -> str:
        """Return `host:port` endpoint string for local test routing."""
        return f"{self.host}:{self.port}"

    async def start(self) -> FakeGoveeBulbServer:
        """Bind ephemeral UDP port on localhost."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _FakeGoveeProtocol(self),
            local_addr=(self.host, self.port),
        )
        self._transport = transport
        sockname = transport.get_extra_info("sockname")
        if sockname:
            self.host = str(sockname[0])
            self.port = int(sockname[1])
        return self

    def close(self) -> None:
        """Close the UDP simulator socket cleanly."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def __aenter__(self) -> FakeGoveeBulbServer:
        return await self.start()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def handle_message(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Process incoming Govee LAN command and update simulated state."""
        msg = payload.get("msg")
        if not isinstance(msg, dict):
            return None
        cmd = msg.get("cmd")
        data = msg.get("data") or {}
        if cmd == "devStatus":
            return {"msg": {"cmd": "devStatus", "data": dict(self.state)}}
        if cmd == "turn":
            self.state["onOff"] = 1 if int(data.get("value", 0)) else 0
            return None
        if cmd == "brightness":
            self.state["brightness"] = max(10, min(100, int(data.get("value", 100))))
            return None
        if cmd == "colorwc":
            if isinstance(data.get("color"), dict):
                self.state["color"] = dict(data["color"])
            self.state["colorTemInKelvin"] = int(data.get("colorTemInKelvin", 0) or 0)
            self.state["onOff"] = 1
            return None
        return None
