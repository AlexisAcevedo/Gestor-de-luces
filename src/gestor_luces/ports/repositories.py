"""Contratos (Puertos Salientes / Driven Ports) de la Arquitectura Hexagonal.

Utilizamos typing.Protocol para aplicar tipado estructural (duck typing estatico).
De esta manera, la capa de aplicacion define QUE necesita del mundo exterior
(control UDP de focos, persistencia en disco, captura de pantalla y audio) sin
acoplarse a COMO se implementa. Esto permite inyectar simuladores o dobles de
prueba sin necesidad de herencia explicita.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gestor_luces.domain.models import Bulb, LightState
from gestor_luces.domain.scenes import CustomScene
from gestor_luces.domain.value_objects import Color


@runtime_checkable
class LightController(Protocol):
    """Puerto para descubrir, consultar y enviar comandos a focos inteligentes en la red."""

    async def discover(self, wait_time: float = 2.5) -> list[Bulb]:
        """Descubre focos disponibles en la red local."""
        ...

    async def probe_bulb(self, ip: str, timeout: float = 1.0) -> Bulb | None:
        """Verifica si una direccion IP especifica responde como un foco valido y lee su estado."""
        ...

    async def get_state(self, ip: str, timeout: float = 1.0) -> LightState | None:
        """Consulta el estado luminico actual del foco en tiempo real."""
        ...

    async def set_power(self, ip: str, is_on: bool, brightness: int | None = None) -> bool:
        """Enciende o apaga el foco, ajustando opcionalmente su brillo."""
        ...

    async def set_brightness(self, ip: str, brightness: int) -> bool:
        """Ajusta el porcentaje de brillo (10-100) manteniendo el modo actual."""
        ...

    async def set_color(self, ip: str, color: Color, brightness: int | None = None) -> bool:
        """Aplica un color RGB al foco, con brillo opcional."""
        ...

    async def set_temperature(self, ip: str, kelvin: int, brightness: int | None = None) -> bool:
        """Aplica una temperatura de blanco en grados Kelvin (2200-6500)."""
        ...

    async def set_scene(
        self,
        ip: str,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
    ) -> bool:
        """Activa una escena predefinida en el firmware del foco."""
        ...

    async def stream_pilot(self, ip: str, color: Color, brightness: int) -> None:
        """Envia un paquete de color y brillo sin esperar confirmacion (fire-and-forget).

        Se disena especificamente para los modos continuos (Ambilight y Musica) donde
        esperar el ACK de cada paquete introduciria latencia perceptible.
        """
        ...


@runtime_checkable
class BulbRepository(Protocol):
    """Puerto para persistir el inventario de focos conocidos y sus nombres."""

    def load_bulbs(self) -> list[Bulb]:
        """Carga la lista de focos guardados previamente."""
        ...

    def save_bulbs(self, bulbs: list[Bulb]) -> None:
        """Guarda la lista actualizada de focos."""
        ...


@runtime_checkable
class SceneRepository(Protocol):
    """Puerto para persistir las escenas personalizadas creadas por el usuario."""

    def load_scenes(self) -> list[CustomScene]:
        """Carga las escenas personalizadas almacenadas."""
        ...

    def save_scenes(self, scenes: list[CustomScene]) -> None:
        """Persiste la coleccion de escenas personalizadas."""
        ...


@runtime_checkable
class ScreenSampler(Protocol):
    """Puerto para muestrear el color predominante de la pantalla (modo Ambilight)."""

    def sample_average_color(self, monitor_index: int = 1) -> Color:
        """Captura una version reducida del monitor indicado y devuelve su color promedio."""
        ...


@runtime_checkable
class AudioSampler(Protocol):
    """Puerto para analizar el audio del sistema en tiempo real (modo Musica)."""

    def sample_audio_metrics(self) -> tuple[float, Color]:
        """Analiza una ventana de audio y devuelve (energia_normalizada_0_a_1, color_espectral)."""
        ...
