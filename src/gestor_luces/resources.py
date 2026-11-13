"""Paths to bundled resources that work from source and from a PyInstaller build."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


def resolve_resource_root() -> Path:
    """Return the directory that contains `ui/` and `assets/`."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir)
    return Path(__file__).resolve().parents[2]


def resolve_asset_path(*parts: str) -> Path:
    """Return a path under `assets/`, e.g. `resolve_asset_path("icon", "app.ico")`."""
    return resolve_resource_root().joinpath("assets", *parts)


def resolve_app_version() -> str:
    """Return the installed package version, or the `pyproject.toml` one when running from
    source."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("gestor-luces")
        except PackageNotFoundError:
            _LOGGER.debug("Package 'gestor-luces' not installed; reading pyproject.toml.")
    # Un build congelado puede quedar sin `importlib.metadata` completo (modulo ausente en
    # `_MEIPASS`): sin metadatos instalados se cae a `pyproject.toml`.
    except ImportError:
        _LOGGER.debug(
            "Could not query importlib.metadata; falling back to pyproject.toml.", exc_info=True
        )
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    # `pyproject.toml` no existe en un build congelado (`OSError`), puede estar corrupto
    # (`TOMLDecodeError` es un `ValueError`) o no declarar `project.version`
    # (`KeyError`/`TypeError`). Sin fuente de version se informa "0.0.0".
    except (OSError, ValueError, KeyError, TypeError):
        _LOGGER.debug("Could not read the version from pyproject.toml.", exc_info=True)
        return "0.0.0"
