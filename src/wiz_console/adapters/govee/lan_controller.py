"""Local LAN UDP adapter for Govee smart lights (`port 4003` JSON protocol)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from typing import Any

from wiz_console.domain.models import Bulb, LightState
from wiz_console.domain.value_objects import Color, LightMode, validate_local_endpoint

_LOGGER = logging.getLogger(__name__)

DEFAULT_GOVEE_CONTROL_PORT = 4003


class _GoveeUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, future: asyncio.Future[dict[str, Any]]) -> None:
        self._future = future

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        if self._future.done():
            return
        try:
            decoded = json.loads(data.decode("utf-8", errors="ignore"))
            if isinstance(decoded, dict):
                self._future.set_result(decoded)
        except json.JSONDecodeError:
            _LOGGER.debug("Discarded malformed Govee UDP payload from %s.", addr[0], exc_info=True)

    def error_received(self, exc: Exception) -> None:
        if not self._future.done():
            self._future.set_exception(exc)


class GoveeLanController:
    """Async UDP adapter implementing `LightController` for local Govee LAN lights."""

    def __init__(
        self,
        port: int = DEFAULT_GOVEE_CONTROL_PORT,
        default_timeout: float = 0.8,
        probe_candidates: list[str] | None = None,
    ) -> None:
        self._port = port
        self._default_timeout = default_timeout
        self._probe_candidates = list(probe_candidates) if probe_candidates is not None else []
        self._stream_sock: socket.socket | None = None

    def _resolve_target(self, endpoint: str) -> tuple[str, int]:
        validated = validate_local_endpoint(endpoint)
        if ":" in validated:
            host, raw_port = validated.rsplit(":", 1)
            return host, int(raw_port)
        return validated, self._port

    def _get_stream_socket(self) -> socket.socket:
        if self._stream_sock is None or self._stream_sock.fileno() < 0:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            self._stream_sock = sock
        return self._stream_sock

    def close(self) -> None:
        """Close the reusable UDP streaming socket if open."""
        if self._stream_sock is not None:
            with contextlib.suppress(OSError):
                self._stream_sock.close()
            self._stream_sock = None

    async def _send_command(
        self,
        endpoint: str,
        cmd: str,
        data: dict[str, Any],
        *,
        expect_reply: bool = False,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        host, port = self._resolve_target(endpoint)
        payload = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode("utf-8")
        if not expect_reply:
            sock = self._get_stream_socket()
            sock.sendto(payload, (host, port))
            return {"ok": True}

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _GoveeUdpProtocol(future),
            remote_addr=(host, port),
        )
        try:
            transport.sendto(payload)
            effective = timeout if timeout is not None else self._default_timeout
            return await asyncio.wait_for(future, timeout=effective)
        except (TimeoutError, OSError):
            return None
        finally:
            transport.close()

    async def discover(self, wait_time: float = 2.5) -> list[Bulb]:
        """Probe configured local Govee endpoints (multicast scan reserved for desktop LAN)."""
        if not self._probe_candidates:
            return []
        results = await asyncio.gather(
            *(
                self.probe_bulb(cand, timeout=min(wait_time, 1.0))
                for cand in self._probe_candidates
            ),
            return_exceptions=True,
        )
        return [b for b in results if isinstance(b, Bulb)]

    async def probe_bulb(self, ip: str, timeout: float = 1.0) -> Bulb | None:
        """Query `devStatus` on a local Govee light and construct a `Bulb` entity."""
        state = await self.get_state(ip, timeout=timeout)
        if state is None:
            return None
        return Bulb(
            ip=ip,
            mac=f"govee:{ip}",
            module_name="GOVEE_LAN_RGB",
            protocol="govee",
            is_online=True,
            state=state,
        )

    async def get_state(self, ip: str, timeout: float = 1.0) -> LightState | None:
        """Query live power/brightness/color state via Govee `devStatus`."""
        resp = await self._send_command(ip, "devStatus", {}, expect_reply=True, timeout=timeout)
        if not isinstance(resp, dict):
            return None
        msg = resp.get("msg")
        data = msg.get("data") if isinstance(msg, dict) else None
        if not isinstance(data, dict):
            return None

        is_on = bool(data.get("onOff", 0))
        bri = max(10, min(100, int(data.get("brightness", 100))))
        kelvin = int(data.get("colorTemInKelvin", 0) or 0)
        raw_color = data.get("color")
        if kelvin >= 2200:
            return LightState(
                is_on=is_on,
                brightness=bri,
                mode=LightMode.TEMPERATURE,
                color=None,
                temperature=max(2200, min(6500, kelvin)),
            )
        if isinstance(raw_color, dict):
            color = Color(
                r=max(0, min(255, int(raw_color.get("r", 255)))),
                g=max(0, min(255, int(raw_color.get("g", 255)))),
                b=max(0, min(255, int(raw_color.get("b", 255)))),
            )
            return LightState(
                is_on=is_on,
                brightness=bri,
                mode=LightMode.RGB,
                color=color,
                temperature=None,
            )
        return LightState(is_on=is_on, brightness=bri, mode=LightMode.TEMPERATURE, temperature=4200)

    async def set_power(self, ip: str, is_on: bool, brightness: int | None = None) -> bool:
        """Turn the Govee fixture on or off with optional brightness."""
        await self._send_command(ip, "turn", {"value": 1 if is_on else 0})
        if brightness is not None and is_on:
            await self.set_brightness(ip, brightness)
        return True

    async def set_brightness(self, ip: str, brightness: int) -> bool:
        """Set Govee brightness (`10..100`)."""
        await self._send_command(ip, "brightness", {"value": max(10, min(100, int(brightness)))})
        return True

    async def set_color(self, ip: str, color: Color, brightness: int | None = None) -> bool:
        """Set RGB color on Govee fixture and optional brightness."""
        await self._send_command(
            ip,
            "colorwc",
            {
                "color": {"r": color.r, "g": color.g, "b": color.b},
                "colorTemInKelvin": 0,
            },
        )
        if brightness is not None:
            await self.set_brightness(ip, brightness)
        return True

    async def set_temperature(self, ip: str, kelvin: int, brightness: int | None = None) -> bool:
        """Set tunable white color temperature on Govee fixture."""
        await self._send_command(
            ip,
            "colorwc",
            {
                "color": {"r": 0, "g": 0, "b": 0},
                "colorTemInKelvin": max(2200, min(6500, int(kelvin))),
            },
        )
        if brightness is not None:
            await self.set_brightness(ip, brightness)
        return True

    async def set_scene(
        self,
        ip: str,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
    ) -> bool:
        """Apply a curated Govee ambient RGB/Kelvin fallback for WiZ scene IDs."""
        warm_fallback = Color(r=255, g=160, b=90)
        return await self.set_color(ip, warm_fallback, brightness=brightness)

    async def stream_pilot(self, ip: str, color: Color, brightness: int) -> None:
        """Send fire-and-forget color and brightness updates for Govee streaming."""
        await self.set_color(ip, color, brightness=brightness)
