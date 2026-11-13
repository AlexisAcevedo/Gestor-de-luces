"""Inventario de focos: descubrimiento, alta manual, renombrado y refresco de estado."""

from __future__ import annotations

import asyncio

from gestor_luces.application.service_context import (
    ServiceContext,
    validate_display_name,
    validate_local_endpoint,
)
from gestor_luces.domain.models import Bulb


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

    async def discover_bulbs(self, wait_time: float = 2.5) -> list[Bulb]:
        """Ejecuta el descubrimiento en la red local y sincroniza el estado real de cada foco.

        Si un foco ya existia en el repositorio local con un nombre personalizado,
        se preserva dicho nombre para no perder la configuracion del usuario.
        """
        discovered = await self._ctx.controller.discover(wait_time=wait_time)
        for bulb in discovered:
            existing = self._ctx.bulbs.get(bulb.ip)
            if existing is not None and not existing.name.startswith("WiZ Bulb ("):
                bulb.name = existing.name
            self._ctx.bulbs[bulb.ip] = bulb

        await self.refresh_states([b.ip for b in discovered])

        if not self._ctx.selected_ips and self._ctx.bulbs:
            self._ctx.selected_ips = list(self._ctx.bulbs.keys())

        self._ctx.persist_bulbs()
        return self._ctx.list_bulbs()

    async def add_manual_bulb(self, ip: str, name: str | None = None) -> Bulb:
        """Registra un foco manualmente por su IP y verifica su estado en la red."""
        cleaned_ip = ip.strip()
        if not cleaned_ip:
            raise ValueError("Bulb IP address cannot be empty.")
        validate_local_endpoint(cleaned_ip)

        probed = await self._ctx.controller.probe_bulb(cleaned_ip)
        validated_name = validate_display_name(name, "Bulb") if (name and name.strip()) else None
        if probed is not None:
            if validated_name:
                probed.name = validated_name
            self._ctx.bulbs[cleaned_ip] = probed
        else:
            fallback_name = validated_name or f"WiZ Bulb ({cleaned_ip})"
            self._ctx.bulbs[cleaned_ip] = Bulb(ip=cleaned_ip, name=fallback_name, is_online=False)

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
            else:
                bulb.is_online = False
            return bulb

        updated = await asyncio.gather(*(_refresh_one(ip) for ip in target_ips))
        return list(updated)
