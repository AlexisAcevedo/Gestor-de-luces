"""Ajustes globales de la consola: idioma y tema."""

from __future__ import annotations

from typing import Any

from wiz_console.application.service_context import ServiceContext
from wiz_console.domain.scenes import get_builtin_scene
from wiz_console.domain.value_objects import SUPPORTED_LANGUAGES, normalize_theme


class SettingsService:
    """Valida, aplica y persiste las preferencias globales de la consola."""

    def __init__(self, context: ServiceContext) -> None:
        self._ctx = context

    def get_language(self) -> str:
        """Devuelve el codigo de idioma activo (`en` o `es`) de la consola."""
        return self._ctx.language

    def set_language(self, language: str) -> str:
        """Valida, actualiza y persiste el idioma activo de la interfaz y la bandeja."""
        cleaned = str(language or "").strip().lower()
        if cleaned not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{language}'. Must be one of {SUPPORTED_LANGUAGES}."
            )
        self._ctx.language = cleaned
        self._ctx.persist_settings()
        return self._ctx.language

    def get_theme(self) -> str:
        """Devuelve el identificador del tema visual activo (`architectural-stone` o
        `atmospheric-dark`)."""
        return self._ctx.theme

    def set_theme(self, theme: str) -> str:
        """Normaliza, actualiza y persiste el tema visual activo de la consola."""
        self._ctx.theme = normalize_theme(theme)
        self._ctx.persist_settings()
        return self._ctx.theme

    def get_tray_hint_seen(self) -> bool:
        """Return whether the one-time hide-to-tray notice has already been shown."""
        return bool(self._ctx.tray_hint_seen)

    def set_tray_hint_seen(self, seen: bool = True) -> bool:
        """Persist whether the one-time hide-to-tray notice has been displayed."""
        self._ctx.tray_hint_seen = bool(seen)
        self._ctx.persist_settings()
        return self._ctx.tray_hint_seen

    def get_auto_sync(self) -> bool:
        """Return whether periodic background polling is enabled."""
        return bool(self._ctx.auto_sync)

    def set_auto_sync(self, enabled: bool) -> bool:
        """Persist whether periodic background polling is enabled."""
        self._ctx.auto_sync = bool(enabled)
        self._ctx.persist_settings()
        return self._ctx.auto_sync

    def get_favorite_builtin_scenes(self) -> list[int]:
        """Return persisted favorite built-in WiZ scene IDs (1-36)."""
        return list(self._ctx.favorite_builtin_scenes)

    def set_favorite_builtin_scenes(self, scene_ids: list[int]) -> list[int]:
        """Validate, deduplicate, and persist favorite built-in WiZ scene IDs."""
        cleaned: list[int] = []
        for raw_id in scene_ids:
            if isinstance(raw_id, bool) or not isinstance(raw_id, int):
                raise ValueError(f"Invalid built-in scene ID: {raw_id!r}.")
            if get_builtin_scene(raw_id) is None:
                raise ValueError(f"Unknown built-in scene ID: {raw_id}.")
            if raw_id not in cleaned:
                cleaned.append(raw_id)
        self._ctx.favorite_builtin_scenes = cleaned
        self._ctx.persist_settings()
        return list(self._ctx.favorite_builtin_scenes)

    def get_ambilight_prefs(self) -> dict[str, Any]:
        """Return persisted Ambilight configuration defaults."""
        return dict(self._ctx.ambilight_prefs)

    def get_music_prefs(self) -> dict[str, Any]:
        """Return persisted Music Sync configuration defaults."""
        return dict(self._ctx.music_prefs)
