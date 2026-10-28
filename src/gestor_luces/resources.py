"""Paths to bundled resources that work from source and from a PyInstaller build."""

from __future__ import annotations

from pathlib import Path
import sys


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
    """Return the installed package version, or the `pyproject.toml` one when running from source."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("gestor-luces")
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except Exception:
        return "0.0.0"
