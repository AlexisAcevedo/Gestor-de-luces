"""Vendor-agnostic composite controller routing bulb commands by IP protocol."""

from __future__ import annotations

import asyncio

from wiz_console.domain.models import DEFAULT_PROTOCOL, SUPPORTED_PROTOCOLS, Bulb, LightState
from wiz_console.domain.value_objects import Color
from wiz_console.ports.repositories import LightController


class CompositeLightController:
    """Routes `LightController` calls across multiple LAN vendor drivers (WiZ, Govee)."""

    def __init__(self, controllers: dict[str, LightController]) -> None:
        self._controllers = {
            proto.lower(): ctrl
            for proto, ctrl in controllers.items()
            if proto.lower() in SUPPORTED_PROTOCOLS
        }
        self._ip_protocols: dict[str, str] = {}

    def register_bulb(self, ip: str, protocol: str = DEFAULT_PROTOCOL) -> None:
        """Associate `ip` with its lighting vendor protocol."""
        cleaned = str(protocol or DEFAULT_PROTOCOL).strip().lower()
        self._ip_protocols[ip] = cleaned if cleaned in self._controllers else DEFAULT_PROTOCOL

    def _resolve_controller(self, ip: str) -> LightController:
        proto = self._ip_protocols.get(ip, DEFAULT_PROTOCOL)
        return self._controllers.get(proto) or next(iter(self._controllers.values()))

    def get_last_rssi(self, ip: str) -> int | None:
        """Delegate RSSI lookup to the controller owning `ip` when supported."""
        ctrl = self._resolve_controller(ip)
        reader = getattr(ctrl, "get_last_rssi", None)
        return reader(ip) if callable(reader) else None

    async def discover(self, wait_time: float = 2.5) -> list[Bulb]:
        """Discover lights across all registered vendor drivers in parallel."""
        batches = await asyncio.gather(
            *(ctrl.discover(wait_time=wait_time) for ctrl in self._controllers.values()),
            return_exceptions=True,
        )
        found: list[Bulb] = []
        for proto, batch in zip(self._controllers.keys(), batches, strict=False):
            if not isinstance(batch, list):
                continue
            for bulb in batch:
                bulb.protocol = proto
                self.register_bulb(bulb.ip, proto)
                found.append(bulb)
        return found

    async def probe_bulb(self, ip: str, timeout: float = 1.0) -> Bulb | None:
        """Probe `ip` via its registered protocol (or fall back across known drivers)."""
        preferred = self._ip_protocols.get(ip)
        ordered: list[tuple[str, LightController]] = []
        if preferred and preferred in self._controllers:
            ordered.append((preferred, self._controllers[preferred]))
        for proto, ctrl in self._controllers.items():
            if proto != preferred:
                ordered.append((proto, ctrl))
        for proto, ctrl in ordered:
            bulb = await ctrl.probe_bulb(ip, timeout=timeout)
            if bulb is not None:
                bulb.protocol = proto
                self.register_bulb(ip, proto)
                return bulb
        return None

    async def get_state(self, ip: str, timeout: float = 1.0) -> LightState | None:
        """Query live luminaire state from the controller owning `ip`."""
        return await self._resolve_controller(ip).get_state(ip, timeout=timeout)

    async def set_power(self, ip: str, is_on: bool, brightness: int | None = None) -> bool:
        """Dispatch power toggle to the controller owning `ip`."""
        return await self._resolve_controller(ip).set_power(ip, is_on, brightness)

    async def set_brightness(self, ip: str, brightness: int) -> bool:
        """Dispatch brightness change to the controller owning `ip`."""
        return await self._resolve_controller(ip).set_brightness(ip, brightness)

    async def set_color(self, ip: str, color: Color, brightness: int | None = None) -> bool:
        """Dispatch RGB color change to the controller owning `ip`."""
        return await self._resolve_controller(ip).set_color(ip, color, brightness)

    async def set_temperature(self, ip: str, kelvin: int, brightness: int | None = None) -> bool:
        """Dispatch tunable white temperature change to the controller owning `ip`."""
        return await self._resolve_controller(ip).set_temperature(ip, kelvin, brightness)

    async def set_scene(
        self,
        ip: str,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
    ) -> bool:
        """Dispatch built-in scene command to the controller owning `ip`."""
        return await self._resolve_controller(ip).set_scene(ip, scene_id, speed, brightness)

    async def stream_pilot(self, ip: str, color: Color, brightness: int) -> None:
        """Dispatch fire-and-forget stream frame to the controller owning `ip`."""
        await self._resolve_controller(ip).stream_pilot(ip, color, brightness)

    def close(self) -> None:
        """Close all underlying vendor controllers cleanly."""
        for ctrl in self._controllers.values():
            ctrl.close()
