"""Catalogo de escenas predefinidas de WiZ y modelo de escenas personalizadas.

Separar el catalogo de escenas en el dominio permite que tanto la interfaz grafica
como los casos de uso conozcan los 36 modos nativos del firmware WiZ (sus IDs,
categorias y soporte de velocidad) sin depender de detalles internos de pywizlight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gestor_luces.domain.value_objects import (
    Brightness,
    Color,
    ColorTemperature,
    LightMode,
    SceneSpeed,
)


@dataclass(frozen=True)
class BuiltInScene:
    """Describe una escena nativa integrada en el firmware de los focos WiZ."""

    scene_id: int
    name: str
    category: str
    supports_speed: bool

    def to_dict(self) -> dict[str, Any]:
        """Serializa la escena nativa para su exposicion hacia la capa de presentacion."""
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "category": self.category,
            "supports_speed": self.supports_speed,
        }


# Catalogo oficial de las 36 escenas nativas de WiZ (IDs 1 a 36 compatibles con pywizlight).
# Las escenas blancas o funcionales fijas tienen supports_speed=False porque el firmware
# ignora el parametro speed cuando no hay animacion de color o transicion activa.
BUILTIN_SCENES: tuple[BuiltInScene, ...] = (
    BuiltInScene(1, "Ocean", "nature", True),
    BuiltInScene(2, "Romance", "ambient", True),
    BuiltInScene(3, "Sunset", "nature", True),
    BuiltInScene(4, "Party", "dynamic", True),
    BuiltInScene(5, "Fireplace", "ambient", True),
    BuiltInScene(6, "Cozy", "ambient", True),
    BuiltInScene(7, "Forest", "nature", True),
    BuiltInScene(8, "Pastel colors", "dynamic", True),
    BuiltInScene(9, "Wake-up", "ambient", True),
    BuiltInScene(10, "Bedtime", "ambient", True),
    BuiltInScene(11, "Warm white", "white", False),
    BuiltInScene(12, "Daylight", "white", False),
    BuiltInScene(13, "Cool white", "white", False),
    BuiltInScene(14, "Night light", "white", False),
    BuiltInScene(15, "Focus", "white", False),
    BuiltInScene(16, "Relax", "white", False),
    BuiltInScene(17, "True colors", "white", False),
    BuiltInScene(18, "TV time", "white", False),
    BuiltInScene(19, "Plantgrowth", "nature", False),
    BuiltInScene(20, "Spring", "nature", True),
    BuiltInScene(21, "Summer", "nature", True),
    BuiltInScene(22, "Fall", "nature", True),
    BuiltInScene(23, "Deep dive", "nature", True),
    BuiltInScene(24, "Jungle", "nature", True),
    BuiltInScene(25, "Mojito", "dynamic", True),
    BuiltInScene(26, "Club", "dynamic", True),
    BuiltInScene(27, "Christmas", "holiday", True),
    BuiltInScene(28, "Halloween", "holiday", True),
    BuiltInScene(29, "Candlelight", "ambient", True),
    BuiltInScene(30, "Golden white", "white", False),
    BuiltInScene(31, "Pulse", "dynamic", True),
    BuiltInScene(32, "Steampunk", "dynamic", True),
    BuiltInScene(33, "Diwali", "holiday", True),
    BuiltInScene(34, "White", "white", False),
    BuiltInScene(35, "Alarm", "dynamic", True),
    BuiltInScene(36, "Snowy sky", "nature", True),
)

_SCENES_BY_ID: dict[int, BuiltInScene] = {scene.scene_id: scene for scene in BUILTIN_SCENES}


def get_builtin_scene(scene_id: int) -> BuiltInScene | None:
    """Busca una escena nativa por su identificador oficial (1-36)."""
    return _SCENES_BY_ID.get(scene_id)


def list_builtin_scenes() -> list[BuiltInScene]:
    """Devuelve la lista completa de las 36 escenas nativas ordenadas por ID."""
    return list(BUILTIN_SCENES)


@dataclass
class CustomScene:
    """Representa un preset o escena personalizada creada y guardada por el usuario."""

    id: str
    name: str
    mode: LightMode
    brightness: int = 100
    color: Color | None = None
    temperature: int | None = None
    built_in_scene_id: int | None = None
    speed: int = 100

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("CustomScene id cannot be empty.")
        if not self.name or not self.name.strip():
            raise ValueError("CustomScene name cannot be empty.")
        Brightness(self.brightness)
        SceneSpeed(self.speed)
        if self.temperature is not None:
            ColorTemperature(self.temperature)
        if self.built_in_scene_id is not None and get_builtin_scene(self.built_in_scene_id) is None:
            raise ValueError(f"Unknown built-in scene ID: {self.built_in_scene_id}.")

    def to_dict(self) -> dict[str, Any]:
        """Convierte la escena personalizada a un diccionario serializable en JSON."""
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode.value,
            "brightness": self.brightness,
            "color": self.color.to_dict() if self.color else None,
            "temperature": self.temperature,
            "built_in_scene_id": self.built_in_scene_id,
            "speed": self.speed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CustomScene:
        """Reconstruye una escena personalizada desde un diccionario JSON."""
        raw_color = data.get("color")
        color = (
            Color(r=int(raw_color["r"]), g=int(raw_color["g"]), b=int(raw_color["b"]))
            if isinstance(raw_color, dict)
            else None
        )
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            mode=LightMode(data["mode"]),
            brightness=int(data.get("brightness", 100)),
            color=color,
            temperature=int(data["temperature"]) if data.get("temperature") is not None else None,
            built_in_scene_id=(
                int(data["built_in_scene_id"])
                if data.get("built_in_scene_id") is not None
                else None
            ),
            speed=int(data.get("speed", 100)),
        )
