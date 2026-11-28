"""Zone / room management: CRUD and target selection against registered bulbs."""

from __future__ import annotations

from uuid import uuid4

from wiz_console.application.service_context import (
    ServiceContext,
    validate_display_name,
    validate_local_endpoint,
)
from wiz_console.domain.models import Zone


class ZoneService:
    """Manages named bulb zones and updates active target selection."""

    def __init__(self, context: ServiceContext) -> None:
        self._ctx = context

    def list_zones(self) -> list[Zone]:
        """Return all saved zones in insertion order."""
        return self._ctx.list_zones()

    def get_zone(self, zone_id: str) -> Zone | None:
        """Look up a saved zone by ID."""
        return self._ctx.zones.get(zone_id)

    def create_or_update_zone(
        self,
        name: str,
        bulb_ips: list[str],
        *,
        zone_id: str | None = None,
        icon: str = "room",
    ) -> Zone:
        """Create a new zone or update an existing one and persist atomically."""
        cleaned_name = validate_display_name(name, "Zone")
        if not isinstance(bulb_ips, list):
            raise ValueError("Zone bulb_ips must be a list of IP strings.")
        cleaned_ips: list[str] = []
        for raw_ip in bulb_ips:
            normalized = validate_local_endpoint(str(raw_ip))
            if normalized not in cleaned_ips:
                cleaned_ips.append(normalized)
        if not cleaned_ips:
            raise ValueError("A zone must include at least one bulb.")

        resolved_id = (
            zone_id.strip() if (zone_id is not None and zone_id.strip()) else uuid4().hex[:8]
        )
        zone = Zone(
            id=resolved_id,
            name=cleaned_name,
            bulb_ips=cleaned_ips,
            icon=icon,
        )
        self._ctx.zones[zone.id] = zone
        self._ctx.persist_zones()
        return zone

    def delete_zone(self, zone_id: str) -> None:
        """Delete an existing zone by ID and persist changes."""
        cleaned_id = zone_id.strip()
        if cleaned_id not in self._ctx.zones:
            raise KeyError(f"Zone '{cleaned_id}' does not exist.")
        del self._ctx.zones[cleaned_id]
        self._ctx.persist_zones()

    def select_zone(self, zone_id: str) -> list[str]:
        """Select registered bulbs belonging to the given zone as active targets."""
        cleaned_id = zone_id.strip()
        zone = self._ctx.zones.get(cleaned_id)
        if zone is None:
            raise KeyError(f"Zone '{cleaned_id}' does not exist.")
        matched = [ip for ip in zone.bulb_ips if ip in self._ctx.bulbs]
        return self._ctx.select_targets(matched)
