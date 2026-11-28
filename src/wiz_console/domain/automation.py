"""Pure domain models and curve math for Circadian lighting and Wake-Up sunrise ramps."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from wiz_console.domain.value_objects import (
    Brightness,
    ColorTemperature,
    parse_strict_int,
    validate_local_endpoint,
)


def _clamp_hour(value: Any, default: float) -> float:
    """Validate an hour-of-day float in `[0.0, 24.0)`."""
    if isinstance(value, bool):
        raise ValueError(f"Hour must be a finite number, got {value!r}.")
    try:
        parsed = float(default if value is None else value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Hour must be a finite number, got {value!r}.") from exc
    if not math.isfinite(parsed) or not (0.0 <= parsed < 24.0):
        raise ValueError(f"Hour must be in [0.0, 24.0), got {parsed!r}.")
    return round(parsed, 2)


@dataclass
class CircadianConfig:
    """Configuration for time-of-day Kelvin and brightness circadian progression."""

    enabled: bool = False
    sunrise_hour: float = 7.0
    sunset_hour: float = 20.0
    day_kelvin: int = 5600
    night_kelvin: int = 2700
    day_brightness: int = 95
    night_brightness: int = 40
    interval_seconds: int = 60

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.sunrise_hour = _clamp_hour(self.sunrise_hour, 7.0)
        self.sunset_hour = _clamp_hour(self.sunset_hour, 20.0)
        if abs(self.sunset_hour - self.sunrise_hour) < 0.25:
            raise ValueError("sunset_hour and sunrise_hour must differ by at least 15 minutes.")
        self.day_kelvin = ColorTemperature(
            parse_strict_int(self.day_kelvin, field="day_kelvin")
        ).kelvin
        self.night_kelvin = ColorTemperature(
            parse_strict_int(self.night_kelvin, field="night_kelvin")
        ).kelvin
        self.day_brightness = Brightness(
            parse_strict_int(self.day_brightness, field="day_brightness")
        ).percent
        self.night_brightness = Brightness(
            parse_strict_int(self.night_brightness, field="night_brightness")
        ).percent
        self.interval_seconds = parse_strict_int(self.interval_seconds, field="interval_seconds")
        if not (10 <= self.interval_seconds <= 3600):
            raise ValueError("interval_seconds must be between 10 and 3600.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize circadian config for JSON persistence and IPC."""
        return {
            "enabled": self.enabled,
            "sunrise_hour": self.sunrise_hour,
            "sunset_hour": self.sunset_hour,
            "day_kelvin": self.day_kelvin,
            "night_kelvin": self.night_kelvin,
            "day_brightness": self.day_brightness,
            "night_brightness": self.night_brightness,
            "interval_seconds": self.interval_seconds,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> CircadianConfig:
        """Reconstruct `CircadianConfig` from persisted or IPC mapping."""
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            sunrise_hour=data.get("sunrise_hour", 7.0),
            sunset_hour=data.get("sunset_hour", 20.0),
            day_kelvin=data.get("day_kelvin", 5600),
            night_kelvin=data.get("night_kelvin", 2700),
            day_brightness=data.get("day_brightness", 95),
            night_brightness=data.get("night_brightness", 40),
            interval_seconds=data.get("interval_seconds", 60),
        )


def evaluate_circadian_target(now_hour: float, config: CircadianConfig) -> tuple[int, int]:
    """Return `(kelvin, brightness)` for `now_hour` in `[0.0, 24.0)` using a cosine curve."""
    hour = float(now_hour) % 24.0
    sunrise = config.sunrise_hour
    sunset = config.sunset_hour
    if sunrise < sunset:
        in_day = sunrise <= hour <= sunset
        span = sunset - sunrise
        elapsed = hour - sunrise
    else:
        in_day = hour >= sunrise or hour <= sunset
        span = (24.0 - sunrise) + sunset
        elapsed = (hour - sunrise) if hour >= sunrise else (24.0 - sunrise + hour)

    if not in_day or span <= 0.0:
        weight = 0.0
    else:
        phase = max(0.0, min(1.0, elapsed / span))
        weight = 0.5 * (1.0 - math.cos(2.0 * math.pi * phase))

    kelvin = round(config.night_kelvin + (config.day_kelvin - config.night_kelvin) * weight)
    brightness = round(
        config.night_brightness + (config.day_brightness - config.night_brightness) * weight
    )
    return (
        max(2200, min(6500, int(kelvin))),
        max(10, min(100, int(brightness))),
    )


@dataclass
class WakeupRampConfig:
    """Configuration for a scheduled or on-demand sunrise wake-up ramp."""

    enabled: bool = False
    target_hour: int = 7
    target_minute: int = 0
    duration_minutes: int = 20
    start_kelvin: int = 2200
    end_kelvin: int = 5000
    start_brightness: int = 10
    end_brightness: int = 100
    target_ips: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.target_hour = parse_strict_int(self.target_hour, field="target_hour")
        self.target_minute = parse_strict_int(self.target_minute, field="target_minute")
        if not (0 <= self.target_hour <= 23):
            raise ValueError("target_hour must be between 0 and 23.")
        if not (0 <= self.target_minute <= 59):
            raise ValueError("target_minute must be between 0 and 59.")
        self.duration_minutes = parse_strict_int(self.duration_minutes, field="duration_minutes")
        if not (1 <= self.duration_minutes <= 60):
            raise ValueError("duration_minutes must be between 1 and 60.")
        self.start_kelvin = ColorTemperature(
            parse_strict_int(self.start_kelvin, field="start_kelvin")
        ).kelvin
        self.end_kelvin = ColorTemperature(
            parse_strict_int(self.end_kelvin, field="end_kelvin")
        ).kelvin
        self.start_brightness = Brightness(
            parse_strict_int(self.start_brightness, field="start_brightness")
        ).percent
        self.end_brightness = Brightness(
            parse_strict_int(self.end_brightness, field="end_brightness")
        ).percent
        cleaned_ips: list[str] = []
        for raw_ip in self.target_ips:
            valid = validate_local_endpoint(str(raw_ip))
            if valid not in cleaned_ips:
                cleaned_ips.append(valid)
        self.target_ips = cleaned_ips

    def to_dict(self) -> dict[str, Any]:
        """Serialize wake-up ramp config for JSON persistence and IPC."""
        return {
            "enabled": self.enabled,
            "target_hour": self.target_hour,
            "target_minute": self.target_minute,
            "duration_minutes": self.duration_minutes,
            "start_kelvin": self.start_kelvin,
            "end_kelvin": self.end_kelvin,
            "start_brightness": self.start_brightness,
            "end_brightness": self.end_brightness,
            "target_ips": list(self.target_ips),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> WakeupRampConfig:
        """Reconstruct `WakeupRampConfig` from persisted or IPC mapping."""
        if not isinstance(data, Mapping):
            return cls()
        raw_ips = data.get("target_ips")
        return cls(
            enabled=bool(data.get("enabled", False)),
            target_hour=data.get("target_hour", 7),
            target_minute=data.get("target_minute", 0),
            duration_minutes=data.get("duration_minutes", 20),
            start_kelvin=data.get("start_kelvin", 2200),
            end_kelvin=data.get("end_kelvin", 5000),
            start_brightness=data.get("start_brightness", 10),
            end_brightness=data.get("end_brightness", 100),
            target_ips=list(raw_ips) if isinstance(raw_ips, list) else [],
        )


def evaluate_wakeup_progress(progress_0_to_1: float, config: WakeupRampConfig) -> tuple[int, int]:
    """Return `(kelvin, brightness)` along a smooth ease-in-out sunrise ramp."""
    p = max(0.0, min(1.0, float(progress_0_to_1)))
    eased = p * p * (3.0 - 2.0 * p)
    kelvin = round(config.start_kelvin + (config.end_kelvin - config.start_kelvin) * eased)
    brightness = round(
        config.start_brightness + (config.end_brightness - config.start_brightness) * eased
    )
    return (
        max(2200, min(6500, int(kelvin))),
        max(10, min(100, int(brightness))),
    )
