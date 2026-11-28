"""Pure domain models and curve math for Circadian lighting and Wake-Up sunrise ramps."""

from __future__ import annotations

import math
import re
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


@dataclass
class SessionTriggersConfig:
    """Opt-in Windows lock/unlock and sleep/resume lighting trigger preferences."""

    off_on_lock: bool = False
    restore_on_unlock: bool = False
    off_on_sleep: bool = False

    def __post_init__(self) -> None:
        self.off_on_lock = bool(self.off_on_lock)
        self.restore_on_unlock = bool(self.restore_on_unlock)
        self.off_on_sleep = bool(self.off_on_sleep)

    def to_dict(self) -> dict[str, bool]:
        """Serialize session trigger preferences for JSON persistence and IPC."""
        return {
            "off_on_lock": self.off_on_lock,
            "restore_on_unlock": self.restore_on_unlock,
            "off_on_sleep": self.off_on_sleep,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> SessionTriggersConfig:
        """Reconstruct `SessionTriggersConfig` from persisted or IPC mapping."""
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            off_on_lock=bool(data.get("off_on_lock", False)),
            restore_on_unlock=bool(data.get("restore_on_unlock", False)),
            off_on_sleep=bool(data.get("off_on_sleep", False)),
        )


CONTEXT_ACTION_TYPES: frozenset[str] = frozenset({"scene", "preset", "temp", "color"})
MAX_CONTEXT_RULES = 32
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _normalize_hex_color(raw: Any, default: str = "#ff2a55") -> str:
    """Validate and normalize a `#rrggbb` color string."""
    cleaned = str(raw if raw is not None else default).strip().lower()
    if not _HEX_RE.fullmatch(cleaned):
        raise ValueError(f"Invalid hex color {raw!r}; expected #rrggbb.")
    return cleaned


@dataclass
class ContextRule:
    """Associates an active Windows executable basename with a target lighting action."""

    process_name: str
    action_type: str = "scene"
    value: str = "12"
    brightness: int = 85
    target_ips: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        proc = str(self.process_name).strip().lower()
        if not proc or len(proc) > 128:
            raise ValueError("process_name must be between 1 and 128 characters.")
        self.process_name = proc
        action = str(self.action_type).strip().lower()
        if action not in CONTEXT_ACTION_TYPES:
            raise ValueError(f"Unsupported context action_type: {self.action_type!r}.")
        self.action_type = action
        val = str(self.value).strip()
        if action == "scene":
            sid = parse_strict_int(int(val), field="value")
            if not (1 <= sid <= 36):
                raise ValueError("scene value must be between 1 and 36.")
            self.value = str(sid)
        elif action == "temp":
            kelvin = ColorTemperature(parse_strict_int(int(val), field="value")).kelvin
            self.value = str(kelvin)
        elif action == "color":
            self.value = _normalize_hex_color(val)
        else:
            if not val or len(val) > 80:
                raise ValueError("preset value must be between 1 and 80 characters.")
            self.value = val
        self.brightness = Brightness(parse_strict_int(self.brightness, field="brightness")).percent
        cleaned_ips: list[str] = []
        for raw_ip in self.target_ips:
            valid = validate_local_endpoint(str(raw_ip))
            if valid not in cleaned_ips:
                cleaned_ips.append(valid)
        self.target_ips = cleaned_ips

    def to_dict(self) -> dict[str, Any]:
        """Serialize context rule for JSON persistence and IPC."""
        return {
            "process_name": self.process_name,
            "action_type": self.action_type,
            "value": self.value,
            "brightness": self.brightness,
            "target_ips": list(self.target_ips),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ContextRule:
        """Reconstruct `ContextRule` from persisted or IPC mapping."""
        raw_ips = data.get("target_ips")
        return cls(
            process_name=str(data.get("process_name", "")),
            action_type=str(data.get("action_type", "scene")),
            value=str(data.get("value", "12")),
            brightness=data.get("brightness", 85),
            target_ips=list(raw_ips) if isinstance(raw_ips, list) else [],
        )


@dataclass
class OnAirConfig:
    """Configuration for local-only microphone/camera On-Air lighting indicator."""

    enabled: bool = False
    watch_mic: bool = True
    watch_camera: bool = True
    color_hex: str = "#ff2a55"
    brightness: int = 90
    target_ips: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.watch_mic = bool(self.watch_mic)
        self.watch_camera = bool(self.watch_camera)
        self.color_hex = _normalize_hex_color(self.color_hex, default="#ff2a55")
        self.brightness = Brightness(parse_strict_int(self.brightness, field="brightness")).percent
        cleaned_ips: list[str] = []
        for raw_ip in self.target_ips:
            valid = validate_local_endpoint(str(raw_ip))
            if valid not in cleaned_ips:
                cleaned_ips.append(valid)
        self.target_ips = cleaned_ips

    def to_dict(self) -> dict[str, Any]:
        """Serialize On-Air configuration for JSON persistence and IPC."""
        return {
            "enabled": self.enabled,
            "watch_mic": self.watch_mic,
            "watch_camera": self.watch_camera,
            "color_hex": self.color_hex,
            "brightness": self.brightness,
            "target_ips": list(self.target_ips),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> OnAirConfig:
        """Reconstruct `OnAirConfig` from persisted or IPC mapping."""
        if not isinstance(data, Mapping):
            return cls()
        raw_ips = data.get("target_ips")
        return cls(
            enabled=bool(data.get("enabled", False)),
            watch_mic=bool(data.get("watch_mic", True)),
            watch_camera=bool(data.get("watch_camera", True)),
            color_hex=data.get("color_hex", "#ff2a55"),
            brightness=data.get("brightness", 90),
            target_ips=list(raw_ips) if isinstance(raw_ips, list) else [],
        )


@dataclass
class ContextAutomationConfig:
    """Opt-in foreground process profiles plus local microphone/camera On-Air rules."""

    enabled: bool = False
    poll_seconds: int = 5
    on_air: OnAirConfig = field(default_factory=OnAirConfig)
    rules: list[ContextRule] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.poll_seconds = parse_strict_int(self.poll_seconds, field="poll_seconds")
        if not (2 <= self.poll_seconds <= 60):
            raise ValueError("poll_seconds must be between 2 and 60.")
        deduped: list[ContextRule] = []
        seen: set[str] = set()
        for rule in self.rules[:MAX_CONTEXT_RULES]:
            if rule.process_name not in seen:
                seen.add(rule.process_name)
                deduped.append(rule)
        self.rules = deduped

    def to_dict(self) -> dict[str, Any]:
        """Serialize context automation settings for JSON persistence and IPC."""
        return {
            "enabled": self.enabled,
            "poll_seconds": self.poll_seconds,
            "on_air": self.on_air.to_dict(),
            "rules": [rule.to_dict() for rule in self.rules],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ContextAutomationConfig:
        """Reconstruct `ContextAutomationConfig` from persisted or IPC mapping."""
        if not isinstance(data, Mapping):
            return cls()
        raw_on_air = data.get("on_air")
        raw_rules = data.get("rules")
        parsed_rules = (
            [ContextRule.from_dict(item) for item in raw_rules if isinstance(item, Mapping)]
            if isinstance(raw_rules, list)
            else []
        )
        return cls(
            enabled=bool(data.get("enabled", False)),
            poll_seconds=data.get("poll_seconds", 5),
            on_air=OnAirConfig.from_dict(raw_on_air if isinstance(raw_on_air, Mapping) else None),
            rules=parsed_rules,
        )


@dataclass
class LocalApiConfig:
    """Opt-in loopback-only local HTTP API configuration."""

    enabled: bool = False
    port: int = 18899
    token: str = ""

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.port = parse_strict_int(self.port, field="port")
        if not (1024 <= self.port <= 65535):
            raise ValueError("Local API port must be between 1024 and 65535.")
        self.token = str(self.token or "").strip()[:128]

    def to_dict(self) -> dict[str, Any]:
        """Serialize local API config for JSON persistence and IPC."""
        return {
            "enabled": self.enabled,
            "port": self.port,
            "token": self.token,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> LocalApiConfig:
        """Reconstruct `LocalApiConfig` from persisted or IPC mapping."""
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            port=data.get("port", 18899),
            token=str(data.get("token", "")),
        )
