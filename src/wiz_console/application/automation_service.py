"""Async circadian lighting, wake-up ramps, session triggers, and context profiles."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from wiz_console.application.bulb_control_service import BulbControlService
from wiz_console.application.service_context import ServiceContext
from wiz_console.domain.automation import (
    CircadianConfig,
    ContextAutomationConfig,
    ContextRule,
    SessionTriggersConfig,
    WakeupRampConfig,
    evaluate_circadian_target,
    evaluate_wakeup_progress,
)
from wiz_console.domain.models import LightState
from wiz_console.domain.value_objects import LightMode

_LOGGER = logging.getLogger(__name__)


class AutomationService:
    """Runs circadian, wake-up, session, and local context automation on the asyncio loop."""

    def __init__(
        self,
        context: ServiceContext,
        bulb_control: BulbControlService,
        now_provider: Callable[[], datetime] = datetime.now,
        wakeup_step_interval: float | None = None,
    ) -> None:
        self._ctx = context
        self._bulb_control = bulb_control
        self._now = now_provider
        self._wakeup_step_interval = wakeup_step_interval
        self._circadian_task: asyncio.Task[None] | None = None
        self._wakeup_task: asyncio.Task[None] | None = None
        self._scheduler_task: asyncio.Task[None] | None = None
        self._context_task: asyncio.Task[None] | None = None
        self._wakeup_active = False
        self._wakeup_progress = 0.0
        self._last_scheduled_day: tuple[int, int, int] | None = None
        self._pre_lock_states: dict[str, LightState] = {}
        self._pre_context_states: dict[str, LightState] = {}
        self._active_context_reason: str | None = None
        self._last_foreground_process: str | None = None

    def get_circadian_config(self) -> dict[str, Any]:
        """Return normalized circadian configuration dictionary."""
        return dict(self._ctx.circadian_config)

    def set_circadian_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Validate, persist, and start/stop the circadian background task."""
        parsed = CircadianConfig.from_dict(config)
        self._ctx.circadian_config = parsed.to_dict()
        self._ctx.persist_settings()
        self._sync_circadian_task(parsed)
        return self.get_circadian_config()

    def get_wakeup_ramp_config(self) -> dict[str, Any]:
        """Return normalized sunrise wake-up ramp configuration dictionary."""
        return dict(self._ctx.wakeup_ramp_config)

    def set_wakeup_ramp_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Validate, persist, and arm/disarm the daily sunrise wake-up scheduler."""
        parsed = WakeupRampConfig.from_dict(config)
        self._ctx.wakeup_ramp_config = parsed.to_dict()
        self._ctx.persist_settings()
        self._sync_scheduler_task(parsed)
        return self.get_wakeup_ramp_config()

    def get_wakeup_ramp_status(self) -> dict[str, Any]:
        """Return live status of the sunrise wake-up ramp."""
        running = (
            self._wakeup_active and self._wakeup_task is not None and not self._wakeup_task.done()
        )
        if not running:
            self._wakeup_active = False
        return {
            "active": running,
            "progress": round(self._wakeup_progress, 3) if running else 0.0,
        }

    def trigger_wakeup_ramp(self, ips: list[str] | None = None) -> dict[str, Any]:
        """Start a sunrise wake-up ramp immediately on the active asyncio loop."""
        cfg = WakeupRampConfig.from_dict(self._ctx.wakeup_ramp_config)
        target_ips = ips if ips is not None else (cfg.target_ips or None)
        loop = asyncio.get_running_loop()
        self.cancel_wakeup_ramp()
        self._wakeup_active = True
        self._wakeup_progress = 0.0
        self._wakeup_task = loop.create_task(
            self._run_wakeup_ramp(cfg, target_ips),
            name="WizConsoleWakeupRamp",
        )
        return self.get_wakeup_ramp_status()

    def cancel_wakeup_ramp(self) -> dict[str, Any]:
        """Cancel any active sunrise wake-up ramp task."""
        if self._wakeup_task is not None and not self._wakeup_task.done():
            self._wakeup_task.cancel()
        self._wakeup_task = None
        self._wakeup_active = False
        self._wakeup_progress = 0.0
        return self.get_wakeup_ramp_status()

    def ensure_background_tasks(self) -> None:
        """Start enabled automation loops when an asyncio event loop is running."""
        self._sync_circadian_task(CircadianConfig.from_dict(self._ctx.circadian_config))
        self._sync_scheduler_task(WakeupRampConfig.from_dict(self._ctx.wakeup_ramp_config))
        self._sync_context_task(ContextAutomationConfig.from_dict(self._ctx.context_automation))

    def shutdown(self) -> None:
        """Cancel all automation asyncio tasks cleanly."""
        for task in (
            self._circadian_task,
            self._wakeup_task,
            self._scheduler_task,
            self._context_task,
        ):
            if task is not None and not task.done():
                task.cancel()
        self._circadian_task = None
        self._wakeup_task = None
        self._scheduler_task = None
        self._context_task = None
        self._wakeup_active = False
        self._wakeup_progress = 0.0
        self._active_context_reason = None

    def get_session_triggers(self) -> dict[str, Any]:
        """Return normalized Windows lock/sleep session trigger settings."""
        return dict(self._ctx.session_triggers)

    def set_session_triggers(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and persist Windows session trigger preferences."""
        parsed = SessionTriggersConfig.from_dict(config)
        self._ctx.session_triggers = parsed.to_dict()
        self._ctx.persist_settings()
        return self.get_session_triggers()

    def _snapshot_active_states(self, target_ips: list[str] | None = None) -> dict[str, LightState]:
        """Capture currently lit bulbs so unlock or exit can restore their prior look."""
        allowed = set(target_ips) if target_ips else None
        snapshot: dict[str, LightState] = {}
        for bulb in self._ctx.list_bulbs():
            if allowed is not None and bulb.ip not in allowed:
                continue
            if bulb.state.is_on:
                snapshot[bulb.ip] = replace(bulb.state)
        return snapshot

    async def _restore_states(self, saved: dict[str, LightState]) -> int:
        """Restore saved per-bulb color, scene, Kelvin, or power state."""
        restored = 0
        for ip, state in saved.items():
            if state.mode == LightMode.RGB and state.color is not None:
                await self._bulb_control.set_color(
                    state.color.r,
                    state.color.g,
                    state.color.b,
                    brightness=state.brightness,
                    ips=[ip],
                )
            elif state.mode == LightMode.SCENE and state.scene_id is not None:
                await self._bulb_control.set_builtin_scene(
                    state.scene_id,
                    brightness=state.brightness,
                    speed=state.speed,
                    ips=[ip],
                )
            elif state.temperature is not None:
                await self._bulb_control.set_temperature(
                    state.temperature, brightness=state.brightness, ips=[ip]
                )
            else:
                await self._bulb_control.set_power(True, ips=[ip])
            restored += 1
        return restored

    async def handle_session_event(self, event: str) -> dict[str, Any]:
        """Apply opt-in lighting actions when Windows reports lock/unlock or suspend/resume."""
        cfg = SessionTriggersConfig.from_dict(self._ctx.session_triggers)
        bulbs = self._ctx.list_bulbs()
        all_ips = [bulb.ip for bulb in bulbs]
        if event == "lock":
            if not cfg.off_on_lock or not all_ips:
                return {"handled": False, "event": event, "affected": 0}
            self._pre_lock_states = self._snapshot_active_states()
            await self._bulb_control.set_power(False, ips=all_ips)
            return {"handled": True, "event": event, "affected": len(all_ips)}
        if event == "suspend":
            if not cfg.off_on_sleep or not all_ips:
                return {"handled": False, "event": event, "affected": 0}
            if cfg.restore_on_unlock and not self._pre_lock_states:
                self._pre_lock_states = self._snapshot_active_states()
            await self._bulb_control.set_power(False, ips=all_ips)
            return {"handled": True, "event": event, "affected": len(all_ips)}
        if event in ("unlock", "resume"):
            if not cfg.restore_on_unlock or not self._pre_lock_states:
                return {"handled": False, "event": event, "affected": 0}
            saved = dict(self._pre_lock_states)
            self._pre_lock_states.clear()
            restored = await self._restore_states(saved)
            return {"handled": True, "event": event, "affected": restored}
        raise ValueError(f"Unsupported session event: {event!r}.")

    def get_context_automation(self) -> dict[str, Any]:
        """Return normalized foreground profile & On-Air configuration."""
        return dict(self._ctx.context_automation)

    def set_context_automation(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Validate, persist, and start/stop local context automation."""
        parsed = ContextAutomationConfig.from_dict(config)
        self._ctx.context_automation = parsed.to_dict()
        self._ctx.persist_settings()
        self._sync_context_task(parsed)
        return self.get_context_automation()

    def get_context_automation_status(self) -> dict[str, Any]:
        """Return live foreground profile and On-Air status for IPC snapshots."""
        supported = (
            self._ctx.context_monitor.is_supported()
            if self._ctx.context_monitor is not None
            else False
        )
        return {
            "supported": supported,
            "active_reason": self._active_context_reason,
            "on_air_active": self._active_context_reason == "on_air",
            "foreground_process": self._last_foreground_process,
        }

    async def _apply_context_rule(self, rule: ContextRule) -> None:
        target_ips = rule.target_ips or None
        if rule.action_type == "scene":
            await self._bulb_control.set_builtin_scene(
                int(rule.value), brightness=rule.brightness, ips=target_ips
            )
        elif rule.action_type == "temp":
            await self._bulb_control.set_temperature(
                int(rule.value), brightness=rule.brightness, ips=target_ips
            )
        elif rule.action_type == "color":
            hx = rule.value
            r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
            await self._bulb_control.set_color(r, g, b, brightness=rule.brightness, ips=target_ips)
        else:
            scene = next(
                (
                    s
                    for s in self._ctx.custom_scenes.values()
                    if s.id == rule.value or s.name.lower() == rule.value.lower()
                ),
                None,
            )
            if scene is not None and scene.color is not None:
                await self._bulb_control.set_color(
                    scene.color.r,
                    scene.color.g,
                    scene.color.b,
                    brightness=scene.brightness,
                    ips=target_ips,
                )
            elif scene is not None and scene.temperature is not None:
                await self._bulb_control.set_temperature(
                    scene.temperature, brightness=scene.brightness, ips=target_ips
                )

    async def evaluate_context_once(self) -> dict[str, Any]:
        """Sample host context once and apply On-Air or matching process lighting with restore."""
        cfg = ContextAutomationConfig.from_dict(self._ctx.context_automation)
        monitor = self._ctx.context_monitor
        if monitor is None or (not cfg.enabled and not cfg.on_air.enabled) or self._streams_busy():
            return self.get_context_automation_status()

        snap = await asyncio.to_thread(monitor.sample)
        self._last_foreground_process = snap.foreground_process

        on_air_triggered = cfg.on_air.enabled and (
            (cfg.on_air.watch_mic and snap.mic_active)
            or (cfg.on_air.watch_camera and snap.camera_active)
        )
        matched_rule: ContextRule | None = None
        if not on_air_triggered and cfg.enabled and snap.foreground_process:
            proc = snap.foreground_process.lower()
            matched_rule = next((r for r in cfg.rules if r.process_name == proc), None)

        desired_reason: str | None = None
        if on_air_triggered:
            desired_reason = "on_air"
        elif matched_rule is not None:
            desired_reason = f"rule:{matched_rule.process_name}"

        if desired_reason == self._active_context_reason:
            return self.get_context_automation_status()

        if desired_reason is None:
            saved = dict(self._pre_context_states)
            self._pre_context_states.clear()
            self._active_context_reason = None
            if saved:
                await self._restore_states(saved)
            return self.get_context_automation_status()

        if self._active_context_reason is None and not self._pre_context_states:
            capture_ips = (
                cfg.on_air.target_ips
                if desired_reason == "on_air"
                else (matched_rule.target_ips if matched_rule is not None else None)
            )
            self._pre_context_states = self._snapshot_active_states(capture_ips or None)

        if desired_reason == "on_air" and self._ctx.list_bulbs():
            hx = cfg.on_air.color_hex
            r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
            await self._bulb_control.set_color(
                r,
                g,
                b,
                brightness=cfg.on_air.brightness,
                ips=cfg.on_air.target_ips or None,
            )
        elif matched_rule is not None and self._ctx.list_bulbs():
            await self._apply_context_rule(matched_rule)

        self._active_context_reason = desired_reason
        return self.get_context_automation_status()

    def _streams_busy(self) -> bool:
        return bool(
            self._ctx.ambilight.get_status().get("active")
            or self._ctx.music_sync.get_status().get("active")
        )

    async def apply_circadian_once(self) -> tuple[int, int] | None:
        """Evaluate current circadian target and apply it unless reactive streams own bulbs."""
        cfg = CircadianConfig.from_dict(self._ctx.circadian_config)
        if not cfg.enabled or self._streams_busy() or not self._ctx.list_bulbs():
            return None
        now = self._now()
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0
        kelvin, brightness = evaluate_circadian_target(hour, cfg)
        await self._bulb_control.set_temperature(kelvin, brightness=brightness)
        return kelvin, brightness

    def _sync_circadian_task(self, cfg: CircadianConfig) -> None:
        if self._circadian_task is not None and not self._circadian_task.done():
            self._circadian_task.cancel()
        self._circadian_task = None
        if not cfg.enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._circadian_task = loop.create_task(
            self._circadian_loop(),
            name="WizConsoleCircadianLoop",
        )

    def _sync_scheduler_task(self, cfg: WakeupRampConfig) -> None:
        if self._scheduler_task is not None and not self._scheduler_task.done():
            self._scheduler_task.cancel()
        self._scheduler_task = None
        if not cfg.enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._scheduler_task = loop.create_task(
            self._wakeup_scheduler_loop(),
            name="WizConsoleWakeupScheduler",
        )

    def _sync_context_task(self, cfg: ContextAutomationConfig) -> None:
        if self._context_task is not None and not self._context_task.done():
            self._context_task.cancel()
        self._context_task = None
        if (not cfg.enabled and not cfg.on_air.enabled) or self._ctx.context_monitor is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._context_task = loop.create_task(
            self._context_loop(),
            name="WizConsoleContextLoop",
        )

    async def _circadian_loop(self) -> None:
        try:
            while True:
                cfg = CircadianConfig.from_dict(self._ctx.circadian_config)
                if not cfg.enabled:
                    break
                try:
                    await self.apply_circadian_once()
                # FRONTERA: background circadian tick touches UDP transport; keep loop alive.
                except Exception:
                    _LOGGER.warning("Circadian lighting tick failed.", exc_info=True)
                await asyncio.sleep(float(cfg.interval_seconds))
        except asyncio.CancelledError:
            raise

    async def _wakeup_scheduler_loop(self) -> None:
        try:
            while True:
                cfg = WakeupRampConfig.from_dict(self._ctx.wakeup_ramp_config)
                if not cfg.enabled:
                    break
                now = self._now()
                today = (now.year, now.month, now.day)
                if (
                    now.hour == cfg.target_hour
                    and now.minute == cfg.target_minute
                    and self._last_scheduled_day != today
                    and not self._wakeup_active
                ):
                    self._last_scheduled_day = today
                    self.trigger_wakeup_ramp()
                await asyncio.sleep(15.0)
        except asyncio.CancelledError:
            raise

    async def _context_loop(self) -> None:
        try:
            while True:
                cfg = ContextAutomationConfig.from_dict(self._ctx.context_automation)
                if not cfg.enabled and not cfg.on_air.enabled:
                    break
                try:
                    await self.evaluate_context_once()
                # FRONTERA: background context monitor inspects OS process/registry state.
                except Exception:
                    _LOGGER.warning("Context automation tick failed.", exc_info=True)
                await asyncio.sleep(float(cfg.poll_seconds))
        except asyncio.CancelledError:
            raise

    async def _run_wakeup_ramp(self, cfg: WakeupRampConfig, target_ips: list[str] | None) -> None:
        steps = 20
        interval = (
            self._wakeup_step_interval
            if self._wakeup_step_interval is not None
            else max(0.5, (cfg.duration_minutes * 60.0) / steps)
        )
        try:
            for idx in range(steps + 1):
                progress = idx / float(steps)
                self._wakeup_progress = progress
                kelvin, brightness = evaluate_wakeup_progress(progress, cfg)
                if self._ctx.list_bulbs() or target_ips:
                    await self._bulb_control.set_temperature(
                        kelvin, brightness=brightness, ips=target_ips
                    )
                if idx < steps:
                    await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        finally:
            self._wakeup_active = False
            self._wakeup_progress = 0.0
            self._wakeup_task = None
