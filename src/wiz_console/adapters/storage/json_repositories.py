"""Implementacion de los puertos BulbRepository y SceneRepository sobre JSON local.

La persistencia se realiza en el directorio de datos de usuario del sistema operativo
(`%LOCALAPPDATA%\\WizConsole` en Windows) para garantizar permisos de escritura incluso
cuando la aplicacion se ejecuta desde un directorio de solo lectura o empaquetado.
En el primer arranque tras actualizar desde `GestorDeLuces`, los archivos existentes se
migran de forma atomica e idempotente conservando los originales como respaldo.
Cada guardado emplea una escritura atomica mediante un archivo temporal hermano (`.tmp`)
seguida de `os.replace`, evitando que un corte de energia o cierre inesperado deje
archivos JSON truncados o corruptos.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from wiz_console.domain.models import Bulb
from wiz_console.domain.scenes import CustomScene
from wiz_console.domain.value_objects import (
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    normalize_language,
    normalize_theme,
    validate_local_endpoint,
)

_LOGGER = logging.getLogger(__name__)

MAX_JSON_FILE_BYTES = 1 * 1024 * 1024
MAX_BULB_RECORDS = 256
MAX_SCENE_RECORDS = 512
_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_BASE_DELAY = 0.02
_MISSING = object()
APP_DATA_DIR_NAME = "WizConsole"
LEGACY_APP_DATA_DIR_NAME = "GestorDeLuces"
UNIX_DATA_DIR_NAME = ".wiz_console"
LEGACY_UNIX_DATA_DIR_NAME = ".gestor_de_luces"
MIGRATED_DATA_FILES = ("bulbs.json", "custom_scenes.json", "settings.json")


def _migrate_legacy_data_dir(legacy_dir: Path, target_dir: Path) -> bool:
    """Copy legacy JSON data files once into ``target_dir`` without deleting ``legacy_dir``."""
    if legacy_dir == target_dir or not legacy_dir.is_dir():
        return False

    migrated_any = False
    for filename in MIGRATED_DATA_FILES:
        src = legacy_dir / filename
        dst = target_dir / filename
        if dst.exists() or src.is_symlink() or not src.is_file():
            continue
        try:
            if src.stat().st_size > MAX_JSON_FILE_BYTES:
                _LOGGER.warning("Skipping oversized legacy data file %s during migration.", src)
                continue
            raw_bytes = src.read_bytes()
            _atomic_write_bytes(dst, raw_bytes)
            migrated_any = True
        except OSError:
            _LOGGER.warning("Failed to migrate legacy data file %s.", src, exc_info=True)
    return migrated_any


def resolve_default_data_dir() -> Path:
    """Resolve and create the user data directory, migrating legacy GestorDeLuces files once.

    On Windows this prioritizes `%LOCALAPPDATA%\\WizConsole` (migrating from
    `%LOCALAPPDATA%\\GestorDeLuces`); on other environments it falls back to `~/.wiz_console`
    (migrating from `~/.gestor_de_luces`).
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data and local_app_data.strip():
        root = Path(local_app_data.strip())
        base_dir = root / APP_DATA_DIR_NAME
        legacy_dir = root / LEGACY_APP_DATA_DIR_NAME
    else:
        home = Path.home()
        base_dir = home / UNIX_DATA_DIR_NAME
        legacy_dir = home / LEGACY_UNIX_DATA_DIR_NAME
    base_dir.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_data_dir(legacy_dir, base_dir)
    return base_dir


def _replace_with_retry(src: Path, dst: Path) -> None:
    """Replace destination file atomically, retrying transient Windows file locks."""
    for attempt in range(_REPLACE_RETRY_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_RETRY_BASE_DELAY * (2**attempt))


def _quarantine_corrupt_file(target_path: Path, reason: str) -> None:
    """Back up a corrupt JSON file before returning defaults so data is not silently lost."""
    _LOGGER.warning(
        "Corrupt JSON file %s (%s); backing up and resetting to defaults.",
        target_path,
        reason,
    )
    backup_path = target_path.with_name(f"{target_path.name}.corrupt")
    try:
        os.replace(target_path, backup_path)
    except OSError:
        _LOGGER.warning("Unable to back up corrupt JSON file %s.", target_path, exc_info=True)


def _atomic_write_bytes(target_path: Path, raw_bytes: bytes) -> None:
    """Write bytes atomically via a sibling temp file, fsync, and os.replace."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_raw = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(target_path.parent),
    )
    tmp_path = Path(tmp_raw)
    replaced = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp_path, target_path)
        replaced = True
    finally:
        # El temporal se descarta ante cualquier salida que no sea el reemplazo exitoso,
        # incluido un `KeyboardInterrupt` durante el apagado. Un `finally` no necesita
        # nombrar `BaseException` y deja propagar la excepcion original intacta.
        if not replaced:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)


def _atomic_write_json(target_path: Path, payload: Any) -> None:
    """Serialize JSON and persist it atomically using ``_atomic_write_bytes``."""
    serialized = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    _atomic_write_bytes(target_path, serialized)


def _read_json_document(target_path: Path) -> Any:
    """Read and parse JSON with file size and recursion depth safeguards."""
    if not target_path.is_file():
        return _MISSING
    try:
        file_size = target_path.stat().st_size
    except OSError:
        _LOGGER.warning("Failed to stat JSON file %s.", target_path, exc_info=True)
        return _MISSING
    if file_size > MAX_JSON_FILE_BYTES:
        _LOGGER.warning(
            "JSON file %s exceeds %d bytes (%d); ignoring.",
            target_path,
            MAX_JSON_FILE_BYTES,
            file_size,
        )
        return _MISSING
    try:
        raw_text = target_path.read_text(encoding="utf-8")
        return json.loads(raw_text)
    except OSError:
        _LOGGER.warning("Failed to read JSON file %s.", target_path, exc_info=True)
        return _MISSING
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        _quarantine_corrupt_file(target_path, type(exc).__name__)
        return _MISSING


def _safe_read_json_list(target_path: Path) -> list[dict[str, Any]]:
    """Lee una lista de objetos JSON desde disco tolerando archivos inexistentes o danados.

    Si el usuario edita manualmente el archivo con errores de sintaxis o aun no existe,
    devolver una lista vacia permite que la consola inicie limpiamente sin bloquearse.
    """
    parsed = _read_json_document(target_path)
    if parsed is _MISSING:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        items = parsed.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    _quarantine_corrupt_file(target_path, "unexpected root type")
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
        if len(records) > MAX_BULB_RECORDS:
            _LOGGER.warning(
                "Bulb repository %s has %d records; truncating to %d.",
                self._file_path,
                len(records),
                MAX_BULB_RECORDS,
            )
            records = records[:MAX_BULB_RECORDS]
        bulbs: list[Bulb] = []
        for record in records:
            try:
                bulb = Bulb.from_dict(record)
                validate_local_endpoint(bulb.ip)
                bulbs.append(bulb)
            except (KeyError, TypeError, ValueError, OverflowError):
                _LOGGER.warning("Skipping invalid bulb record in %s.", self._file_path)
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
        if len(records) > MAX_SCENE_RECORDS:
            _LOGGER.warning(
                "Scene repository %s has %d records; truncating to %d.",
                self._file_path,
                len(records),
                MAX_SCENE_RECORDS,
            )
            records = records[:MAX_SCENE_RECORDS]
        scenes: list[CustomScene] = []
        for record in records:
            try:
                scenes.append(CustomScene.from_dict(record))
            except (KeyError, TypeError, ValueError, OverflowError):
                _LOGGER.warning("Skipping invalid scene record in %s.", self._file_path)
                continue
        return scenes

    def save_scenes(self, scenes: list[CustomScene]) -> None:
        """Persiste atomicamente la lista de escenas personalizadas."""
        payload = [scene.to_dict() for scene in scenes]
        _atomic_write_json(self._file_path, payload)


DEFAULT_SETTINGS: dict[str, Any] = {
    "language": DEFAULT_LANGUAGE,
    "theme": DEFAULT_THEME,
}


class JsonSettingsRepository:
    """Persiste las preferencias globales de la consola (`language` y `theme`) en
    `settings.json`."""

    def __init__(self, data_dir: Path | None = None, filename: str = "settings.json") -> None:
        self._data_dir = data_dir if data_dir is not None else resolve_default_data_dir()
        self._file_path = self._data_dir / filename

    @property
    def file_path(self) -> Path:
        """Expone la ruta del archivo JSON subyacente para diagnostico y pruebas."""
        return self._file_path

    def load_settings(self) -> dict[str, Any]:
        """Recupera las preferencias guardadas tolerando archivos inexistentes o corruptos.

        Si el archivo no existe, contiene sintaxis JSON invalida o valores desconocidos,
        retorna los valores por defecto (`en` y `architectural-stone`) para garantizar un arranque
        seguro.
        """
        parsed = _read_json_document(self._file_path)
        if parsed is _MISSING:
            return dict(DEFAULT_SETTINGS)

        if not isinstance(parsed, dict):
            _quarantine_corrupt_file(self._file_path, "expected JSON object")
            return dict(DEFAULT_SETTINGS)

        language = normalize_language(parsed.get("language", DEFAULT_LANGUAGE))
        theme = normalize_theme(parsed.get("theme", DEFAULT_THEME))
        merged = dict(DEFAULT_SETTINGS)
        merged.update(parsed)
        merged["language"] = language
        merged["theme"] = theme
        if "tray_hint_seen" in merged:
            merged["tray_hint_seen"] = bool(merged["tray_hint_seen"])
        return merged

    def save_settings(self, settings: dict[str, Any]) -> None:
        """Valida y persiste atomicamente el diccionario de preferencias."""
        language = normalize_language(settings.get("language", DEFAULT_LANGUAGE))
        theme = normalize_theme(settings.get("theme", DEFAULT_THEME))
        payload = dict(DEFAULT_SETTINGS)
        payload.update(settings)
        payload["language"] = language
        payload["theme"] = theme
        if "tray_hint_seen" in payload:
            payload["tray_hint_seen"] = bool(payload["tray_hint_seen"])
        _atomic_write_json(self._file_path, payload)
