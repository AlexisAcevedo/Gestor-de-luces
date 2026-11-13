"""Sesion de captura WASAPI Loopback: abre, alimenta y libera el stream no bloqueante.

WASAPI tiene una particularidad critica de diseno: cuando ninguna aplicacion del sistema
emite sonido, el motor de audio de Windows detiene el reloj de transferencia del endpoint y
deja de invocar el callback de captura (o bloquea indefinidamente cualquier llamada sincrona
a `stream.read()`). Para evitar que un hilo trabajador quede congelado en silencio, la
sesion abre el flujo en modo no bloqueante (`stream_callback`) y registra la marca de
tiempo monotonica (`time.monotonic()`) de cada bloque PCM recibido: es el muestreador quien
decide, con ese reloj, cuando asumir silencio acustico.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2

#: Errores documentados de PortAudio/WASAPI al consultar o abrir un endpoint.
#:
#: `pyaudiowpatch` envuelve a PortAudio sobre ctypes: un endpoint ausente, ocupado o con un
#: formato que el driver rechaza llega como `OSError`, un indice invalido como `ValueError`,
#: y un descriptor de dispositivo incompleto como `KeyError`/`TypeError`. `ImportError` es la
#: pila de audio no instalada, que el modulo degrada a silencio de reposo. Cualquier otra
#: excepcion es un defecto y propaga al bucle que muestrea, que la registra por iteracion.
WASAPI_DEVICE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    ImportError,
)


def _release_native_resource(resource: Any, method_name: str, description: str) -> None:
    """Libera un recurso nativo sin dejar que el fallo de liberacion propague.

    FRONTERA: cerrar un stream de PortAudio o terminar `PyAudio` corre en las rutas de
    limpieza (cambio de dispositivo, fin del muestreo y apagado de la app). La DLL puede
    fallar de cualquier forma mientras libera handles, y una excepcion ahi abortaria el
    resto de la secuencia de limpieza; se registra con traza y se continua.
    """
    method = getattr(resource, method_name, None)
    if not callable(method):
        return
    try:
        method()
    # FRONTERA (ver el docstring): la liberacion de un recurso nativo nunca propaga.
    except Exception:
        _LOGGER.debug("Ignoring error while %s.", description, exc_info=True)


class WasapiLoopbackStreamSession:
    """Envoltorio del contenedor PortAudio y del stream loopback activo."""

    def __init__(
        self,
        frames_per_buffer: int = 2048,
        pyaudio_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._frames_per_buffer = max(256, int(frames_per_buffer))
        self._pyaudio_factory = pyaudio_factory
        self._lock = threading.Lock()
        self._pa: Any | None = None
        self._stream: Any | None = None
        self._active_device_index: int | None = None
        self._sample_rate: int = DEFAULT_SAMPLE_RATE
        self._channels: int = DEFAULT_CHANNELS
        self._latest_pcm_bytes: bytes = b""
        self._last_chunk_monotonic: float = 0.0

    @property
    def sample_rate(self) -> int:
        """Frecuencia de muestreo negociada con el endpoint (48000 Hz por defecto)."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Cantidad de canales negociada con el endpoint (estereo por defecto)."""
        return self._channels

    def create_pyaudio(self) -> Any:
        """Instancia el contenedor PortAudio/WASAPI bajo demanda."""
        if self._pyaudio_factory is not None:
            return self._pyaudio_factory()
        import pyaudiowpatch as pyaudio

        return pyaudio.PyAudio()

    def read(self) -> tuple[bytes, float, int, int]:
        """Devuelve el ultimo bloque PCM, su marca de tiempo y el formato negociado."""
        with self._lock:
            return (
                self._latest_pcm_bytes,
                self._last_chunk_monotonic,
                self._sample_rate,
                self._channels,
            )

    def ensure_stream(self, requested_device_index: int | None) -> bool:
        """Abre o reconfigura el stream no bloqueante de captura WASAPI Loopback."""
        normalized_req = (
            int(requested_device_index)
            if (requested_device_index is not None and int(requested_device_index) >= 0)
            else None
        )
        if (
            self._stream is not None
            and self._pa is not None
            and self._active_device_index == normalized_req
        ):
            return True

        self.close()

        try:
            import pyaudiowpatch as pyaudio

            pa_float32 = getattr(pyaudio, "paFloat32", 1)
            pa_continue = getattr(pyaudio, "paContinue", 0)
        except ImportError:
            # Sin `pyaudiowpatch` el modo Musica queda en silencio de reposo, no en error.
            _LOGGER.debug("pyaudiowpatch is unavailable; using the default format.", exc_info=True)
            pa_float32 = 1
            pa_continue = 0

        try:
            pa = self.create_pyaudio()
            device_info: dict[str, Any] | None = None

            if normalized_req is not None:
                try:
                    candidate = pa.get_device_info_by_index(normalized_req)
                    if candidate and int(candidate.get("maxInputChannels", 0)) > 0:
                        device_info = dict(candidate)
                except WASAPI_DEVICE_ERRORS:
                    # El indice pedido ya no existe (o dejo de ser de entrada): se cae al
                    # loopback por defecto.
                    _LOGGER.debug(
                        "Requested loopback device %s is unavailable.",
                        normalized_req,
                        exc_info=True,
                    )
                    device_info = None

            if device_info is None:
                device_info = dict(pa.get_default_wasapi_loopback())

            sample_rate = int(float(device_info.get("defaultSampleRate", 48000)))
            channels = max(1, int(device_info.get("maxInputChannels", 2) or 2))
            dev_idx = int(device_info["index"])

            def _audio_callback(
                in_data: bytes | None,
                frame_count: int,
                time_info: Any,
                status_flags: int,
            ) -> tuple[None, int]:
                if in_data:
                    with self._lock:
                        self._latest_pcm_bytes = bytes(in_data)
                        self._last_chunk_monotonic = time.monotonic()
                return (None, pa_continue)

            stream = pa.open(
                format=pa_float32,
                channels=channels,
                rate=sample_rate,
                frames_per_buffer=self._frames_per_buffer,
                input=True,
                input_device_index=dev_idx,
                stream_callback=_audio_callback,
            )
            if hasattr(stream, "start_stream"):
                stream.start_stream()

            with self._lock:
                self._pa = pa
                self._stream = stream
                self._active_device_index = normalized_req
                self._sample_rate = sample_rate
                self._channels = channels
            return True
        except WASAPI_DEVICE_ERRORS:
            _LOGGER.debug(
                "Could not open WASAPI loopback stream; returning standby silence.",
                exc_info=True,
            )
            self.close()
            return False

    def close(self) -> None:
        """Cierra de forma segura el stream de captura y libera la sesion WASAPI."""
        with self._lock:
            stream = self._stream
            pa = self._pa
            self._stream = None
            self._pa = None
            self._active_device_index = None
            self._latest_pcm_bytes = b""
            self._last_chunk_monotonic = 0.0

        if stream is not None:
            _release_native_resource(stream, "stop_stream", "stopping the WASAPI stream")
            _release_native_resource(stream, "close", "closing the WASAPI stream")

        if pa is not None:
            _release_native_resource(pa, "terminate", "terminating PyAudio")
