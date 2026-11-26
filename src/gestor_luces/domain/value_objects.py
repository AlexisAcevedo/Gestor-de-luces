"""Objetos de valor inmutables del dominio (Value Objects).

En Arquitectura Limpia y Hexagonal, los Value Objects encapsulan las reglas
de negocio primitivas (rangos de RGB, Kelvin, brillo y velocidad) para que sea
imposible construir un estado invalido en cualquier capa del sistema. Al ser
inmutables (frozen=True), se pueden compartir entre hilos y tareas asincronas
sin riesgo de efectos secundarios.
"""

from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass
from enum import StrEnum

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "es")
DEFAULT_LANGUAGE: str = "en"
SUPPORTED_THEMES: tuple[str, ...] = ("architectural-stone", "atmospheric-dark")
DEFAULT_THEME: str = "architectural-stone"

DEFAULT_WIZ_UDP_PORT = 38899
MIN_LOOPBACK_PORT = 1024
MAX_UDP_PORT = 65535

_ALLOWED_LOCAL_IPV4_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
)
_RESERVED_LINK_LOCAL_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("169.254.0.0/24"),
    ipaddress.IPv4Network("169.254.255.0/24"),
)


def parse_strict_int(value: object, *, field: str) -> int:
    """Parse an integer value strictly, rejecting booleans and non-finite floats."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{field} must be a finite integer.")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} must be an integer.")
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(f"{field} must be an integer.") from exc
    raise ValueError(f"{field} must be an integer.")


def validate_local_endpoint(value: str) -> str:
    """Validate that an endpoint targets a unicast local IPv4 host and allowed UDP port.

    Accepts ``a.b.c.d`` or ``a.b.c.d:port``. Loopback endpoints permit unprivileged
    ports ``1024..65535`` (for local simulators); LAN endpoints only permit the
    standard WiZ UDP port ``38899`` (or no explicit port). Rejects unspecified,
    multicast, reserved, network, and broadcast addresses.
    """
    if not isinstance(value, str):
        raise ValueError(f"Invalid bulb IPv4 address: {value!r}")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"Invalid bulb IPv4 address: {value!r}")

    host, sep, raw_port = cleaned.partition(":")
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError as exc:
        raise ValueError(f"Invalid bulb IPv4 address: {value!r}") from exc

    if address.is_unspecified or address.is_multicast or address.is_reserved:
        raise ValueError(f"Bulb address must be a unicast local host: {value!r}")

    matched_net = next((net for net in _ALLOWED_LOCAL_IPV4_NETWORKS if address in net), None)
    if matched_net is None:
        raise ValueError(f"Bulb address must be on the local network: {value!r}")
    if address == matched_net.network_address or address == matched_net.broadcast_address:
        raise ValueError(f"Bulb address cannot be a network or broadcast address: {value!r}")
    if address.packed[-1] == 255:
        raise ValueError(f"Bulb address cannot be a directed broadcast address: {value!r}")
    if any(address in reserved for reserved in _RESERVED_LINK_LOCAL_NETWORKS):
        raise ValueError(f"Bulb address cannot be in reserved link-local range: {value!r}")

    if sep:
        if not (raw_port.isascii() and raw_port.isdigit()):
            raise ValueError(f"Invalid bulb port: {value!r}")
        port = int(raw_port)
        if address.is_loopback:
            if not (MIN_LOOPBACK_PORT <= port <= MAX_UDP_PORT):
                raise ValueError(f"Invalid loopback bulb port: {value!r}")
        elif port != DEFAULT_WIZ_UDP_PORT:
            raise ValueError(f"LAN bulb port must be {DEFAULT_WIZ_UDP_PORT}: {value!r}")

    return cleaned


def normalize_language(value: object) -> str:
    """Normaliza un codigo de idioma hacia uno de los idiomas soportados."""
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in SUPPORTED_LANGUAGES:
            return cleaned
    return DEFAULT_LANGUAGE


def normalize_theme(value: object) -> str:
    """Normaliza un identificador de tema hacia uno de los temas soportados."""
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in SUPPORTED_THEMES:
            return cleaned
    return DEFAULT_THEME


class LightMode(StrEnum):
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
        if not isinstance(hex_str, str):
            raise ValueError(f"Invalid hex color format: {hex_str!r}. Expected 6 hex digits.")
        cleaned = hex_str.strip()
        if cleaned.startswith("#"):
            cleaned = cleaned[1:]
        if len(cleaned) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in cleaned):
            raise ValueError(f"Invalid hex color format: {hex_str!r}. Expected 6 hex digits.")
        return cls(
            r=int(cleaned[0:2], 16),
            g=int(cleaned[2:4], 16),
            b=int(cleaned[4:6], 16),
        )

    def lerp(self, other: Color, t: float) -> Color:
        """Interpola linealmente entre este color y otro segun el factor t en [0.0, 1.0].

        Se utiliza en el suavizado exponencial (EMA) para evitar parpadeos bruscos
        cuando el color promedio de la pantalla o el espectro de audio cambian rapido.
        """
        if isinstance(t, bool):
            raise ValueError("Interpolation factor t must be a finite number.")
        try:
            numeric_t = float(t)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Interpolation factor t must be a finite number.") from exc
        if not math.isfinite(numeric_t):
            raise ValueError("Interpolation factor t must be a finite number.")
        clamped_t = max(0.0, min(1.0, numeric_t))
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
                f"Color temperature must be an integer between 2200 and 6500 K, "
                f"got {self.kelvin!r}."
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
