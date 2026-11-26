"""Capa de Dominio de Gestor de Luces.

Exporta las entidades, objetos de valor y catalogos puros sin dependencias externas.
"""

from gestor_luces.domain.models import Bulb, LightState
from gestor_luces.domain.scenes import (
    BUILTIN_SCENES,
    BuiltInScene,
    CustomScene,
    get_builtin_scene,
    list_builtin_scenes,
)
from gestor_luces.domain.value_objects import (
    DEFAULT_WIZ_UDP_PORT,
    Brightness,
    Color,
    ColorTemperature,
    LightMode,
    SceneSpeed,
    validate_local_endpoint,
)

__all__ = [
    "BUILTIN_SCENES",
    "Brightness",
    "Bulb",
    "BuiltInScene",
    "Color",
    "ColorTemperature",
    "CustomScene",
    "DEFAULT_WIZ_UDP_PORT",
    "LightMode",
    "LightState",
    "SceneSpeed",
    "get_builtin_scene",
    "list_builtin_scenes",
    "validate_local_endpoint",
]
