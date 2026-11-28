"""Entidades principales del dominio: LightState y Bulb.

Estas clases modelan la realidad del negocio (el estado luminico actual de cada
foco) sin conocer absolutamente nada sobre sockets UDP, archivos JSON ni PyWebView.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wiz_console.domain.scenes import get_builtin_scene
from wiz_console.domain.value_objects import (
    Brightness,
    Color,
    ColorTemperature,
    LightMode,
    SceneSpeed,
    parse_strict_int,
    validate_local_endpoint,
)


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
        if not isinstance(self.mode, LightMode):
            raise ValueError(f"Invalid light mode: {self.mode!r}")
        Brightness(self.brightness)
        SceneSpeed(self.speed)
        if self.temperature is not None:
            ColorTemperature(self.temperature)
        if self.color is not None and not isinstance(self.color, Color):
            raise ValueError(f"Invalid color value: {self.color!r}")
        if self.scene_id is not None and (
            isinstance(self.scene_id, bool) or not isinstance(self.scene_id, int)
        ):
            raise ValueError(f"Invalid scene_id value: {self.scene_id!r}")
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
            Color(
                r=parse_strict_int(raw_color["r"], field="color.r"),
                g=parse_strict_int(raw_color["g"], field="color.g"),
                b=parse_strict_int(raw_color["b"], field="color.b"),
            )
            if isinstance(raw_color, dict)
            else None
        )
        raw_mode = data.get("mode", LightMode.TEMPERATURE.value)
        mode = (
            LightMode(raw_mode)
            if raw_mode in {m.value for m in LightMode}
            else LightMode.TEMPERATURE
        )
        raw_scene_name = data.get("scene_name")
        scene_name = raw_scene_name if isinstance(raw_scene_name, str) and raw_scene_name else None
        return cls(
            is_on=bool(data.get("is_on", False)),
            brightness=parse_strict_int(data.get("brightness", 100), field="brightness"),
            mode=mode,
            color=color,
            temperature=(
                parse_strict_int(data["temperature"], field="temperature")
                if data.get("temperature") is not None
                else None
            ),
            scene_id=(
                parse_strict_int(data["scene_id"], field="scene_id")
                if data.get("scene_id") is not None
                else None
            ),
            scene_name=scene_name,
            speed=parse_strict_int(data.get("speed", 100), field="speed"),
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
        if not isinstance(self.ip, str):
            raise ValueError("Bulb IP address must be a string.")
        self.ip = self.ip.strip()
        if not self.ip:
            raise ValueError("Bulb IP address cannot be empty.")
        self.ip = validate_local_endpoint(self.ip)
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
        raw_ip = data["ip"]
        if not isinstance(raw_ip, str):
            raise ValueError("Bulb ip must be a string.")
        raw_mac = data.get("mac", "unknown")
        raw_name = data.get("name", "")
        raw_module = data.get("module_name", "ESP01_SHRGB1C_31")
        for field_name, field_val in (
            ("mac", raw_mac),
            ("name", raw_name),
            ("module_name", raw_module),
        ):
            if field_val is not None and not isinstance(field_val, str):
                raise ValueError(f"Bulb {field_name} must be a string.")
        raw_state = data.get("state")
        state = LightState.from_dict(raw_state) if isinstance(raw_state, dict) else LightState()
        return cls(
            ip=raw_ip,
            mac=raw_mac if raw_mac is not None else "unknown",
            name=raw_name if raw_name is not None else "",
            module_name=raw_module if raw_module is not None else "ESP01_SHRGB1C_31",
            is_online=bool(data.get("is_online", True)),
            state=state,
        )
