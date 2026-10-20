"""Objetos de valor inmutables del dominio (Value Objects).

En Arquitectura Limpia y Hexagonal, los Value Objects encapsulan las reglas
de negocio primitivas (rangos de RGB, Kelvin, brillo y velocidad) para que sea
imposible construir un estado invalido en cualquier capa del sistema. Al ser
inmutables (frozen=True), se pueden compartir entre hilos y tareas asincronas
sin riesgo de efectos secundarios.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LightMode(str, Enum):
    """Define los modos de operacion mutuamente excluyentes de un foco WiZ."""

    RGB = "rgb"
    TEMPERATURE = "temperature"
    SCENE = "scene"


@dataclass(frozen=True)
class Color:
    """Representa un color RGB validado en el rango estandar de 8 bits por canal (0-255).

    Incluye interpolacion lineal (lerp) en el propio dominio porque las transiciones
    suaves de Ambilight y el modo Musica dependen de promediar colores sin acoplarse
    a librerias graficas externas.
    """

    r: int
    g: int
    b: int

    def __post_init__(self) -> None:
        for channel_name, value in (("r", self.r), ("g", self.g), ("b", self.b)):
            if not isinstance(value, int) or isinstance(value, bool) or not (0 <= value <= 255):
                raise ValueError(
                    f"Channel '{channel_name}' must be an integer between 0 and 255, got {value!r}."
                )

    def to_hex(self) -> str:
        """Convierte el color a formato hexadecimal CSS (#RRGGBB) para la capa de interfaz."""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    @classmethod
    def from_hex(cls, hex_str: str) -> Color:
        """Construye un Color a partir de una cadena hexadecimal (#RRGGBB o RRGGBB)."""
        cleaned = hex_str.strip().lstrip("#")
        if len(cleaned) != 6:
            raise ValueError(f"Invalid hex color format: {hex_str!r}. Expected 6 hex digits.")
        try:
            r = int(cleaned[0:2], 16)
            g = int(cleaned[2:4], 16)
            b = int(cleaned[4:6], 16)
        except ValueError as exc:
            raise ValueError(f"Invalid hex color format: {hex_str!r}.") from exc
        return cls(r=r, g=g, b=b)

    def lerp(self, other: Color, t: float) -> Color:
        """Interpola linealmente entre este color y otro segun el factor t en [0.0, 1.0].

        Se utiliza en el suavizado exponencial (EMA) para evitar parpadeos bruscos
        cuando el color promedio de la pantalla o el espectro de audio cambian rapido.
        """
        clamped_t = max(0.0, min(1.0, float(t)))
        r = round(self.r + (other.r - self.r) * clamped_t)
        g = round(self.g + (other.g - self.g) * clamped_t)
        b = round(self.b + (other.b - self.b) * clamped_t)
        return Color(r=r, g=g, b=b)

    def max_channel_delta(self, other: Color) -> int:
        """Calcula la diferencia maxima absoluta entre canales respecto a otro color."""
        return max(abs(self.r - other.r), abs(self.g - other.g), abs(self.b - other.b))

    def to_dict(self) -> dict[str, int | str]:
        """Serializa el color a un diccionario simple apto para JSON."""
        return {"r": self.r, "g": self.g, "b": self.b, "hex": self.to_hex()}


@dataclass(frozen=True)
class ColorTemperature:
    """Representa la temperatura de color blanco en grados Kelvin (2200K a 6500K).

    El hardware Philips WiZ A60 soporta fisicamente desde blanco muy calido (2200K)
    hasta luz dia fria (6500K). Validar este rango en el dominio evita enviar comandos
    UDP que el firmware del foco rechazaria o recortaria silenciosamente.
    """

    kelvin: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kelvin, int)
            or isinstance(self.kelvin, bool)
            or not (2200 <= self.kelvin <= 6500)
        ):
            raise ValueError(
                f"Color temperature must be an integer between 2200 and 6500 K, got {self.kelvin!r}."
            )


@dataclass(frozen=True)
class Brightness:
    """Representa el nivel de brillo del foco en porcentaje (10% a 100%).

    El protocolo WiZ no admite valores de dimming inferiores a 10% (para apagar el
    foco se utiliza state=False). Centralizar esta restriccion aqui protege a todos
    los casos de uso.
    """

    percent: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.percent, int)
            or isinstance(self.percent, bool)
            or not (10 <= self.percent <= 100)
        ):
            raise ValueError(
                f"Brightness must be an integer between 10 and 100, got {self.percent!r}."
            )


@dataclass(frozen=True)
class SceneSpeed:
    """Representa la velocidad de transicion de una escena dinamica WiZ (10 a 200)."""

    value: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, int)
            or isinstance(self.value, bool)
            or not (10 <= self.value <= 200)
        ):
            raise ValueError(
                f"Scene speed must be an integer between 10 and 200, got {self.value!r}."
            )
