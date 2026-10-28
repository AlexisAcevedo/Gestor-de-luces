"""Implementacion de los puertos BulbRepository y SceneRepository sobre JSON local.

La persistencia se realiza en el directorio de datos de usuario del sistema operativo
(`%LOCALAPPDATA%\\GestorDeLuces` en Windows) para garantizar permisos de escritura incluso
cuando la aplicacion se ejecuta desde un directorio de solo lectura o empaquetado.
Cada guardado emplea una escritura atomica mediante un archivo temporal hermano (`.tmp`)
seguida de `os.replace`, evitando que un corte de energia o cierre inesperado deje
archivos JSON truncados o corruptos.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from gestor_luces.domain.models import Bulb
from gestor_luces.domain.scenes import CustomScene


def resolve_default_data_dir() -> Path:
    """Determina y crea el directorio de datos local para la configuracion del usuario.

    En Windows prioriza `%LOCALAPPDATA%\\GestorDeLuces` siguiendo las convenciones de
    aplicaciones de escritorio nativas; en otros entornos o si la variable no existe,
    recurre a `~/.gestor_de_luces`.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data and local_app_data.strip():
        base_dir = Path(local_app_data.strip()) / "GestorDeLuces"
    else:
        base_dir = Path.home() / ".gestor_de_luces"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _atomic_write_json(target_path: Path, payload: Any) -> None:
    """Escribe una estructura JSON de forma atomica usando un archivo temporal y os.replace.

    Escribir directamente sobre el archivo destino podria corromper el inventario si el
    proceso termina a mitad de la operacion de E/S. Al volcar primero en un archivo `.tmp`
    en el mismo volumen y reemplazarlo atomicamente, el archivo destino siempre contiene
    la version anterior integra o la version nueva completa.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    fd, tmp_raw = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(target_path.parent),
    )
    tmp_path = Path(tmp_raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target_path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _safe_read_json_list(target_path: Path) -> list[dict[str, Any]]:
    """Lee una lista de objetos JSON desde disco tolerando archivos inexistentes o danados.

    Si el usuario edita manualmente el archivo con errores de sintaxis o aun no existe,
    devolver una lista vacia permite que la consola inicie limpiamente sin bloquearse.
    """
    if not target_path.is_file():
        return []
    try:
        raw_text = target_path.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)
    except (OSError, json.JSONDecodeError, ValueError):
        return []

    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        items = parsed.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


class JsonBulbRepository:
    """Persiste el inventario de focos conocidos y sus nombres amigables en `bulbs.json`."""

    def __init__(self, data_dir: Path | None = None, filename: str = "bulbs.json") -> None:
        self._data_dir = data_dir if data_dir is not None else resolve_default_data_dir()
        self._file_path = self._data_dir / filename

    @property
    def file_path(self) -> Path:
        """Expone la ruta del archivo JSON subyacente para diagnostico y pruebas."""
        return self._file_path

    def load_bulbs(self) -> list[Bulb]:
        """Recupera los focos guardados descartando entradas malformadas sin abortar la carga."""
        records = _safe_read_json_list(self._file_path)
        bulbs: list[Bulb] = []
        for record in records:
            try:
                bulbs.append(Bulb.from_dict(record))
            except (KeyError, TypeError, ValueError):
                continue
        return bulbs

    def save_bulbs(self, bulbs: list[Bulb]) -> None:
        """Persiste atomicamente la coleccion completa de focos registrados."""
        payload = [bulb.to_dict() for bulb in bulbs]
        _atomic_write_json(self._file_path, payload)


class JsonSceneRepository:
    """Persiste los presets y escenas personalizadas del usuario en `custom_scenes.json`."""

    def __init__(self, data_dir: Path | None = None, filename: str = "custom_scenes.json") -> None:
        self._data_dir = data_dir if data_dir is not None else resolve_default_data_dir()
        self._file_path = self._data_dir / filename

    @property
    def file_path(self) -> Path:
        """Expone la ruta del archivo JSON subyacente para diagnostico y pruebas."""
        return self._file_path

    def load_scenes(self) -> list[CustomScene]:
        """Recupera las escenas personalizadas validando sus rangos de dominio al cargar."""
        records = _safe_read_json_list(self._file_path)
        scenes: list[CustomScene] = []
        for record in records:
            try:
                scenes.append(CustomScene.from_dict(record))
            except (KeyError, TypeError, ValueError):
                continue
        return scenes

    def save_scenes(self, scenes: list[CustomScene]) -> None:
        """Persiste atomicamente la lista de escenas personalizadas."""
        payload = [scene.to_dict() for scene in scenes]
        _atomic_write_json(self._file_path, payload)


SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "es")
DEFAULT_SETTINGS: dict[str, Any] = {"language": "en"}


class JsonSettingsRepository:
    """Persiste las preferencias globales de la consola (como el idioma) en `settings.json`."""

    def __init__(self, data_dir: Path | None = None, filename: str = "settings.json") -> None:
        self._data_dir = data_dir if data_dir is not None else resolve_default_data_dir()
        self._file_path = self._data_dir / filename

    @property
    def file_path(self) -> Path:
        """Expone la ruta del archivo JSON subyacente para diagnostico y pruebas."""
        return self._file_path

    def load_settings(self) -> dict[str, Any]:
        """Recupera las preferencias guardadas tolerando archivos inexistentes o corruptos.

        Si el archivo no existe, contiene sintaxis JSON invalida o un codigo de idioma
        desconocido, retorna el idioma por defecto (`en`) para garantizar un arranque seguro.
        """
        if not self._file_path.is_file():
            return dict(DEFAULT_SETTINGS)
        try:
            raw_text = self._file_path.read_text(encoding="utf-8")
            parsed = json.loads(raw_text)
        except (OSError, json.JSONDecodeError, ValueError):
            return dict(DEFAULT_SETTINGS)

        if not isinstance(parsed, dict):
            return dict(DEFAULT_SETTINGS)

        raw_lang = str(parsed.get("language", "en")).strip().lower()
        language = raw_lang if raw_lang in SUPPORTED_LANGUAGES else "en"
        merged = dict(DEFAULT_SETTINGS)
        merged.update(parsed)
        merged["language"] = language
        return merged

    def save_settings(self, settings: dict[str, Any]) -> None:
        """Valida y persiste atomicamente el diccionario de preferencias."""
        raw_lang = str(settings.get("language", "en")).strip().lower()
        language = raw_lang if raw_lang in SUPPORTED_LANGUAGES else "en"
        payload = dict(DEFAULT_SETTINGS)
        payload.update(settings)
        payload["language"] = language
        _atomic_write_json(self._file_path, payload)

