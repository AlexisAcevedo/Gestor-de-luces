"""Adaptadores de captura de audio del sistema para el modo de sincronizacion musical."""

from gestor_luces.adapters.audio.wasapi_sampler import (
    VALID_MUSIC_PALETTES,
    WasapiLoopbackSampler,
    analyze_pcm_audio_frame,
)

__all__ = [
    "VALID_MUSIC_PALETTES",
    "WasapiLoopbackSampler",
    "analyze_pcm_audio_frame",
]

