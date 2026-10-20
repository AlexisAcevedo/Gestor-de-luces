"""Adaptador de captura de pantalla rapida para el modo Ambilight."""

from gestor_luces.adapters.ambilight.mss_sampler import (
    MssScreenSampler,
    extract_color_and_brightness_from_bgra,
)

__all__ = [
    "MssScreenSampler",
    "extract_color_and_brightness_from_bgra",
]
