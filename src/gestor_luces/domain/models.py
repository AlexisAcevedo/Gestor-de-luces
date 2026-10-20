"""Entidades principales del dominio: LightState, Bulb y Group.

Estas clases modelan la realidad del negocio (el estado luminico actual de cada
foco y su agrupacion logica) sin conocer absolutamente nada sobre sockets UDP,
archivos JSON ni PyWebView.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gestor_luces.domain.scenes import get_builtin_scene
from gestor_luces.domain.value_objects import Color, LightMode


@dataclass
class LightState:
    """Representa una instantanea del estado luminico de un foco WiZ."""

    is_on: bool = False
    brightness: int = 100
    mode: LightMode = LightMode.TEMPERATURE
    color: Color | None = None
    temperature: int | None = 4200
    scene_id: int | None = None
    scene_name: str | None = None
    speed: int = 100

    def __post_init__(self) -> None:
        if self.scene_id is not None and not self.scene_name:
            builtin = get_builtin_scene(self.scene_id)
            if builtin is not None:
                self.scene_name = builtin.name

    def to_dict(self) -> dict[str, Any]:
        """Serializa el estado en un diccionario limpio para la interfaz JS/HTML."""
        return {
            "is_on": self.is_on,
            "brightness": self.brightness,
            "mode": self.mode.value,
            "color": self.color.to_dict() if self.color else None,
            "temperature": self.temperature,
            "scene_id": self.scene_id,
            "scene_name": self.scene_name,
            "speed": self.speed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LightState:
        """Reconstruye el estado luminico a partir de un diccionario deserializado de JSON."""
        raw_color = data.get("color")
        color = (
            Color(r=int(raw_color["r"]), g=int(raw_color["g"]), b=int(raw_color["b"]))
            if isinstance(raw_color, dict)
            else None
        )
        raw_mode = data.get("mode", LightMode.TEMPERATURE.value)
        mode = LightMode(raw_mode) if raw_mode in {m.value for m in LightMode} else LightMode.TEMPERATURE
        return cls(
            is_on=bool(data.get("is_on", False)),
            brightness=int(data.get("brightness", 100)),
            mode=mode,
            color=color,
            temperature=int(data["temperature"]) if data.get("temperature") is not None else None,
            scene_id=int(data["scene_id"]) if data.get("scene_id") is not None else None,
            scene_name=str(data["scene_name"]) if data.get("scene_name") else None,
            speed=int(data.get("speed", 100)),
        )


@dataclass
class Bulb:
    """Entidad que representa un foco inteligente WiZ identificado por su IP y MAC."""

    ip: str
    mac: str = "unknown"
    name: str = ""
    module_name: str = "ESP01_SHRGB1C_31"
    is_online: bool = True
    state: LightState = field(default_factory=LightState)

    def __post_init__(self) -> None:
        self.ip = self.ip.strip()
        if not self.ip:
            raise ValueError("Bulb IP address cannot be empty.")
        if not self.name or not self.name.strip():
            self.name = f"WiZ Bulb ({self.ip})"

    def to_dict(self) -> dict[str, Any]:
        """Serializa la entidad completa (metadatos + estado) para la UI o persistencia."""
        return {
            "ip": self.ip,
            "mac": self.mac,
            "name": self.name,
            "module_name": self.module_name,
            "is_online": self.is_online,
            "state": self.state.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bulb:
        """Reconstruye una entidad Bulb completa desde su representacion persistida en JSON."""
        raw_state = data.get("state")
        state = LightState.from_dict(raw_state) if isinstance(raw_state, dict) else LightState()
        return cls(
            ip=str(data["ip"]),
            mac=str(data.get("mac", "unknown")),
            name=str(data.get("name", "")),
            module_name=str(data.get("module_name", "ESP01_SHRGB1C_31")),
            is_online=bool(data.get("is_online", True)),
            state=state,
        )


@dataclass
class Group:
    """Agrupacion logica de multiples focos para control sincronizado por habitacion o zona."""

    id: str
    name: str
    bulb_ips: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("Group id cannot be empty.")
        if not self.name or not self.name.strip():
            raise ValueError("Group name cannot be empty.")

    def to_dict(self) -> dict[str, Any]:
        """Serializa el grupo de focos a un diccionario simple."""
        return {
            "id": self.id,
            "name": self.name,
            "bulb_ips": list(self.bulb_ips),
        }
