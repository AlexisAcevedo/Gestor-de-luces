"""Ajustes globales de la consola: idioma y tema."""

from __future__ import annotations

from wiz_console.application.service_context import ServiceContext
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
