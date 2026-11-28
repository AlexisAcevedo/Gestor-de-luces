"""Inventario de focos: descubrimiento, alta manual, renombrado, baja y refresco de estado."""

from __future__ import annotations

import asyncio
import logging

from wiz_console.application.service_context import (
    ServiceContext,
    validate_display_name,
    validate_local_endpoint,
)
from wiz_console.domain.models import DEFAULT_PROTOCOL, SUPPORTED_PROTOCOLS, Bulb

_LOGGER = logging.getLogger(__name__)


def _normalize_mac(mac: str | None) -> str | None:
    """Normalize a bulb MAC address, returning None for empty or unknown placeholders."""
    if not mac:
        return None
    cleaned = mac.strip().lower().replace(":", "").replace("-", "")
    if not cleaned or cleaned == "unknown" or cleaned == "000000000000":
        return None
    return cleaned


class BulbInventoryService:
    """Mantiene el inventario de focos del contexto y su estado real en la red."""

    def __init__(self, context: ServiceContext) -> None:
        self._ctx = context

    def list_bulbs(self) -> list[Bulb]:
        """Devuelve la lista de todos los focos registrados actualmente."""
        return self._ctx.list_bulbs()

    def get_bulb(self, ip: str) -> Bulb | None:
        """Obtiene un foco registrado por su direccion IP."""
        return self._ctx.get_bulb(ip)

    def _find_by_mac(self, normalized_mac: str, *, exclude_ip: str) -> str | None:
        for ip, existing in self._ctx.bulbs.items():
            if ip == exclude_ip:
                continue
            if _normalize_mac(existing.mac) == normalized_mac:
                return ip
        return None

    def _reconcile_bulb_references(self, old_ip: str, new_ip: str | None) -> None:
        """Propagate bulb removal (new_ip=None) or DHCP IP change into zones and scenes."""
        zones_changed = False
        for zone in self._ctx.zones.values():
            if old_ip not in zone.bulb_ips:
                continue
            updated: list[str] = []
            for ip in zone.bulb_ips:
                if ip == old_ip:
                    if new_ip is not None and new_ip not in updated:
                        updated.append(new_ip)
                elif ip not in updated:
                    updated.append(ip)
            zone.bulb_ips = updated
            zones_changed = True
        if zones_changed:
            self._ctx.persist_zones()

        scenes_changed = False
        for scene in self._ctx.custom_scenes.values():
            if not scene.bulb_states or old_ip not in scene.bulb_states:
                continue
            captured = scene.bulb_states.pop(old_ip)
            if new_ip is not None and new_ip not in scene.bulb_states:
                scene.bulb_states[new_ip] = captured
            scene.bulb_states = scene.bulb_states or None
            scenes_changed = True
        if scenes_changed:
            self._ctx.persist_scenes()

    async def discover_bulbs(self, wait_time: float = 2.5) -> list[Bulb]:
        """Discover bulbs on the LAN, reconcile DHCP IP changes by MAC, and sync live states."""
        discovered = await self._ctx.controller.discover(wait_time=wait_time)
        targets_changed = False
        for bulb in discovered:
            existing = self._ctx.bulbs.get(bulb.ip)
            norm_mac = _normalize_mac(bulb.mac)
            if existing is None and norm_mac is not None:
                old_ip = self._find_by_mac(norm_mac, exclude_ip=bulb.ip)
                if old_ip is not None:
                    existing = self._ctx.bulbs.pop(old_ip)
                    if old_ip in self._ctx.selected_ips:
                        updated_targets: list[str] = []
                        for target in self._ctx.selected_ips:
                            replacement = bulb.ip if target == old_ip else target
                            if replacement not in updated_targets:
                                updated_targets.append(replacement)
                        self._ctx.selected_ips = updated_targets
                        targets_changed = True
                    self._reconcile_bulb_references(old_ip, bulb.ip)
                    _LOGGER.info(
                        "Reconciled bulb MAC %s after DHCP IP change: %s -> %s",
                        norm_mac,
                        old_ip,
                        bulb.ip,
                    )
            if existing is not None and not existing.name.startswith("WiZ Bulb ("):
                bulb.name = existing.name
            if existing is not None and bulb.fw_version is None:
                bulb.fw_version = existing.fw_version
            if existing is not None and bulb.rssi is None:
                bulb.rssi = existing.rssi
            self._ctx.bulbs[bulb.ip] = bulb

        await self.refresh_states([b.ip for b in discovered])

        if not self._ctx.selected_ips and self._ctx.bulbs:
            self._ctx.selected_ips = list(self._ctx.bulbs.keys())
            targets_changed = True

        if targets_changed:
            resolved = self._ctx.get_target_ips()
            self._ctx.ambilight.update_targets(resolved)
            self._ctx.music_sync.update_targets(resolved)
            self._ctx.persist_settings()

        self._ctx.persist_bulbs()
        return self._ctx.list_bulbs()

    async def add_manual_bulb(
        self,
        ip: str,
        name: str | None = None,
        protocol: str = DEFAULT_PROTOCOL,
    ) -> Bulb:
        """Registra un foco manualmente por su IP y verifica su estado en la red."""
        cleaned_ip = ip.strip()
        if not cleaned_ip:
            raise ValueError("Bulb IP address cannot be empty.")
        validate_local_endpoint(cleaned_ip)
        cleaned_proto = str(protocol or DEFAULT_PROTOCOL).strip().lower()
        if cleaned_proto not in SUPPORTED_PROTOCOLS:
            raise ValueError(f"Unsupported lighting protocol: {protocol!r}.")
        registrar = getattr(self._ctx.controller, "register_bulb", None)
        if callable(registrar):
            registrar(cleaned_ip, cleaned_proto)

        probed = await self._ctx.controller.probe_bulb(cleaned_ip)
        validated_name = validate_display_name(name, "Bulb") if (name and name.strip()) else None
        if probed is not None:
            probed.protocol = cleaned_proto
            if validated_name:
                probed.name = validated_name
            self._ctx.bulbs[cleaned_ip] = probed
        else:
            prefix = "Govee Bulb" if cleaned_proto == "govee" else "WiZ Bulb"
            fallback_name = validated_name or f"{prefix} ({cleaned_ip})"
            self._ctx.bulbs[cleaned_ip] = Bulb(
                ip=cleaned_ip,
                name=fallback_name,
                protocol=cleaned_proto,
                is_online=False,
            )

        if cleaned_ip not in self._ctx.selected_ips:
            self._ctx.selected_ips.append(cleaned_ip)

        self._ctx.persist_bulbs()
        return self._ctx.bulbs[cleaned_ip]

    def rename_bulb(self, ip: str, new_name: str) -> Bulb:
        """Cambia el nombre amigable de un foco registrado y guarda el cambio."""
        bulb = self._ctx.bulbs.get(ip)
        if bulb is None:
            raise KeyError(f"Bulb with IP '{ip}' is not registered.")
        bulb.name = validate_display_name(new_name, "Bulb")
        self._ctx.persist_bulbs()
        return bulb

    def remove_bulb(self, ip: str) -> Bulb:
        """Remove a registered bulb by IP, update active stream targets, and persist."""
        cleaned_ip = ip.strip()
        bulb = self._ctx.bulbs.pop(cleaned_ip, None)
        if bulb is None:
            raise KeyError(f"Bulb with IP '{cleaned_ip}' is not registered.")
        if cleaned_ip in self._ctx.selected_ips:
            self._ctx.selected_ips = [item for item in self._ctx.selected_ips if item != cleaned_ip]
            resolved = self._ctx.get_target_ips()
            self._ctx.ambilight.update_targets(resolved)
            self._ctx.music_sync.update_targets(resolved)
            self._ctx.persist_settings()
        self._reconcile_bulb_references(cleaned_ip, None)
        self._ctx.persist_bulbs()
        return bulb

    async def refresh_states(self, ips: list[str] | None = None) -> list[Bulb]:
        """Consulta en paralelo el estado real (getPilot) de los focos indicados.

        Esto garantiza que si alguien apago o cambio el color del foco desde la
        llave de pared o la app movil de WiZ, nuestra aplicacion refleje la verdad.
        """
        target_ips = self._ctx.get_target_ips(ips)
        if not target_ips:
            return []

        async def _refresh_one(ip: str) -> Bulb:
            bulb = self._ctx.ensure_bulb_entry(ip)
            live_state = await self._ctx.controller.get_state(ip)
            if live_state is not None:
                bulb.state = live_state
                bulb.is_online = True
                rssi_reader = getattr(self._ctx.controller, "get_last_rssi", None)
                if callable(rssi_reader):
                    latest_rssi = rssi_reader(ip)
                    if isinstance(latest_rssi, int) and not isinstance(latest_rssi, bool):
                        bulb.rssi = latest_rssi
            else:
                bulb.is_online = False
            return bulb

        updated = await asyncio.gather(*(_refresh_one(ip) for ip in target_ips))
        return list(updated)
