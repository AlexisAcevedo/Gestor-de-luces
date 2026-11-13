"""Ajustes globales de la consola: idioma y tema."""

from __future__ import annotations

from gestor_luces.application.service_context import ServiceContext
from gestor_luces.domain.value_objects import SUPPORTED_LANGUAGES, normalize_theme


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
