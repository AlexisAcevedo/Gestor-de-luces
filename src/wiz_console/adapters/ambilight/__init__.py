"""Adaptador de captura de pantalla rapida para el modo Ambilight."""

from wiz_console.adapters.ambilight.mss_sampler import (
    VALID_AMBILIGHT_REGIONS,
    MssScreenSampler,
    detect_letterbox_bounds,
    extract_color_and_brightness_from_bgra,
    extract_region_colors_from_bgra,
)

__all__ = [
    "MssScreenSampler",
    "VALID_AMBILIGHT_REGIONS",
    "detect_letterbox_bounds",
    "extract_color_and_brightness_from_bgra",
    "extract_region_colors_from_bgra",
]
