"""Alias del modulo de contratos para facilitar importaciones desde ports.interfaces."""

from gestor_luces.ports.repositories import (
    AudioSampler,
    BulbRepository,
    LightController,
    SceneRepository,
    ScreenSampler,
)

__all__ = [
    "AudioSampler",
    "BulbRepository",
    "LightController",
    "SceneRepository",
    "ScreenSampler",
]
