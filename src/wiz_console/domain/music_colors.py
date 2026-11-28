"""Pure domain color mapping and per-band frequency assignment for Music Sync."""

from __future__ import annotations

from collections.abc import Mapping

from wiz_console.domain.value_objects import Color

VALID_MUSIC_PALETTES = ("spectrum", "club", "chill", "custom")
VALID_BAND_ASSIGNMENTS = ("full", "bass", "mid", "treble")
STANDBY_BRIGHTNESS_FLOOR = 12
DEFAULT_CUSTOM_PALETTE: dict[str, str] = {
    "bass": "#ff2a55",
    "mid": "#22e58b",
    "treble": "#389bff",
}


def normalize_custom_palette(palette: Mapping[str, str] | None) -> dict[str, str]:
    """Validate and normalize a custom 3-band hex palette (`bass`, `mid`, `treble`)."""
    normalized = dict(DEFAULT_CUSTOM_PALETTE)
    if palette is None:
        return normalized
    if not isinstance(palette, Mapping):
        raise ValueError("custom_palette must be an object mapping bass, mid, and treble colors.")
    for band in ("bass", "mid", "treble"):
        if band in palette and palette[band] is not None:
            normalized[band] = Color.from_hex(str(palette[band])).to_hex()
    return normalized


def standby_color_for_palette(
    palette_mode: str,
    custom_palette: Mapping[str, str] | None = None,
) -> Color:
    """Return a subtle standby tint matching the active music palette during silence."""
    normalized = palette_mode.strip().lower() if isinstance(palette_mode, str) else "spectrum"
    if normalized == "club":
        return Color(r=64, g=18, b=52)
    if normalized == "chill":
        return Color(r=18, g=52, b=78)
    if normalized == "custom":
        base = Color.from_hex(normalize_custom_palette(custom_palette)["bass"])
        return Color(r=max(12, base.r // 5), g=max(12, base.g // 5), b=max(12, base.b // 5))
    return Color(r=56, g=34, b=24)


def map_bands_to_color(
    bass: float,
    mid: float,
    treble: float,
    rms: float,
    palette_mode: str,
    custom_palette: Mapping[str, str] | None = None,
) -> Color:
    """Transform normalized Bass/Mid/Treble energy into a saturated RGB Color."""
    max_band = max(bass, mid, treble)
    if max_band <= 1e-4 and rms <= 1e-4:
        return standby_color_for_palette(palette_mode, custom_palette)

    inv_max = 1.0 / max(1e-6, max_band)
    rel_bass = bass * inv_max
    rel_mid = mid * inv_max
    rel_treble = treble * inv_max
    intensity = max(0.45, min(1.0, max(rms, max_band)))

    normalized = palette_mode.strip().lower() if isinstance(palette_mode, str) else "spectrum"
    if normalized == "club":
        raw_r = (rel_bass * 1.00 + rel_treble * 0.72 + rel_mid * 0.08) * 255.0
        raw_g = (rel_mid * 0.92 + rel_treble * 0.35 + rel_bass * 0.05) * 255.0
        raw_b = (rel_mid * 0.95 + rel_treble * 0.95 + rel_bass * 0.42) * 255.0
    elif normalized == "chill":
        raw_r = (rel_treble * 0.68 + rel_bass * 0.10 + rel_mid * 0.06) * 255.0
        raw_g = (rel_mid * 0.92 + rel_bass * 0.38 + rel_treble * 0.45) * 255.0
        raw_b = (rel_bass * 0.95 + rel_treble * 0.98 + rel_mid * 0.68) * 255.0
    elif normalized == "custom":
        palette = normalize_custom_palette(custom_palette)
        c_bass = Color.from_hex(palette["bass"])
        c_mid = Color.from_hex(palette["mid"])
        c_treble = Color.from_hex(palette["treble"])
        denom = max(1e-6, rel_bass + rel_mid + rel_treble)
        # Preserve pure saturation when one band dominates while blending chords smoothly.
        mix_scale = min(1.0, max(rel_bass, rel_mid, rel_treble) / denom * 1.35)
        raw_r = (rel_bass * c_bass.r + rel_mid * c_mid.r + rel_treble * c_treble.r) / denom
        raw_g = (rel_bass * c_bass.g + rel_mid * c_mid.g + rel_treble * c_treble.g) / denom
        raw_b = (rel_bass * c_bass.b + rel_mid * c_mid.b + rel_treble * c_treble.b) / denom
        raw_r = min(255.0, raw_r * (0.85 + 0.15 * mix_scale))
        raw_g = min(255.0, raw_g * (0.85 + 0.15 * mix_scale))
        raw_b = min(255.0, raw_b * (0.85 + 0.15 * mix_scale))
    else:
        raw_r = (rel_bass * 0.98 + rel_mid * 0.10) * 255.0
        raw_g = (rel_mid * 0.98 + rel_bass * 0.12 + rel_treble * 0.08) * 255.0
        raw_b = (rel_treble * 0.98 + rel_mid * 0.18) * 255.0

    return Color(
        r=max(0, min(255, round(raw_r * intensity))),
        g=max(0, min(255, round(raw_g * intensity))),
        b=max(0, min(255, round(raw_b * intensity))),
    )


def resolve_band_frame(
    band_assignment: str,
    *,
    bass: float,
    mid: float,
    treble: float,
    rms: float,
    base_color: Color,
    base_brightness: int,
    palette_mode: str = "spectrum",
    custom_palette: Mapping[str, str] | None = None,
    beat: bool = False,
    beat_boost: bool = True,
    audio_brightness: bool = True,
) -> tuple[Color, int]:
    """Compute per-bulb `(Color, brightness)` for a band assignment and optional beat pulse."""
    band = band_assignment.strip().lower() if isinstance(band_assignment, str) else "full"
    pulse = 12 if (beat and beat_boost) else 0
    if band not in ("bass", "mid", "treble"):
        return base_color, max(10, min(100, int(base_brightness) + pulse))

    isolated = {
        "bass": (bass, 0.0, 0.0, bass),
        "mid": (0.0, mid, 0.0, mid),
        "treble": (0.0, 0.0, treble, treble),
    }[band]
    band_color = map_bands_to_color(
        bass=isolated[0],
        mid=isolated[1],
        treble=isolated[2],
        rms=isolated[3],
        palette_mode=palette_mode,
        custom_palette=custom_palette,
    )
    if audio_brightness:
        band_bri = round(
            STANDBY_BRIGHTNESS_FLOOR + min(1.0, isolated[3]) * (100.0 - STANDBY_BRIGHTNESS_FLOOR)
        )
        effective_bri = max(10, min(100, band_bri + pulse))
    else:
        effective_bri = max(10, min(100, int(base_brightness) + pulse))
    return band_color, effective_bri
