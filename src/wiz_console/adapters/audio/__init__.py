"""Adaptadores de captura de audio del sistema para el modo de sincronizacion musical."""

from wiz_console.adapters.audio.wasapi_sampler import (
    VALID_BAND_ASSIGNMENTS,
    VALID_MUSIC_PALETTES,
    BeatDetector,
    WasapiLoopbackSampler,
    analyze_pcm_audio_frame,
)

__all__ = [
    "BeatDetector",
    "VALID_BAND_ASSIGNMENTS",
    "VALID_MUSIC_PALETTES",
    "WasapiLoopbackSampler",
    "analyze_pcm_audio_frame",
]
