"""Simulated v0.4.3 -> v0.5.0 in-place upgrade and release metadata verification."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import pytest

from wiz_console.adapters.storage.json_repositories import (
    APP_DATA_DIR_NAME,
    LEGACY_APP_DATA_DIR_NAME,
    JsonBulbRepository,
    JsonSceneRepository,
    JsonSettingsRepository,
    resolve_default_data_dir,
)
from wiz_console.adapters.system.windows_autostart import (
    DEFAULT_VALUE_NAME,
    LEGACY_VALUE_NAME,
    RUN_KEY_PATH,
    WindowsRegistryAutostart,
)
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.resources import resolve_app_version


class _FakeKey:
    """Context manager wrapper returned by `_InMemoryRegistry`."""

    def __init__(self, store: dict[str, tuple[int, str]], sub_key: str) -> None:
        self._store = store
        self._sub_key = sub_key

    def __enter__(self) -> _FakeKey:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _InMemoryRegistry:
    """Minimal winreg stand-in verifying HKCU Run migration without mutating Windows."""

    HKEY_CURRENT_USER = 1
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.values: dict[str, tuple[int, str]] = {
            name: (self.REG_SZ, val) for name, val in (initial or {}).items()
        }

    def OpenKey(self, root: int, sub_key: str, _res: int, _access: int) -> _FakeKey:
        if root != self.HKEY_CURRENT_USER or sub_key != RUN_KEY_PATH:
            raise FileNotFoundError(sub_key)
        return _FakeKey(self.values, sub_key)

    def CreateKeyEx(self, root: int, sub_key: str, _res: int, _access: int) -> _FakeKey:
        return self.OpenKey(root, sub_key, _res, _access)

    def QueryValueEx(self, key: _FakeKey, value_name: str) -> tuple[str, int]:
        if value_name not in key._store:
            raise FileNotFoundError(value_name)
        kind, value = key._store[value_name]
        return value, kind

    def SetValueEx(self, key: _FakeKey, value_name: str, _res: int, kind: int, val: str) -> None:
        key._store[value_name] = (kind, val)

    def DeleteValue(self, key: _FakeKey, value_name: str) -> None:
        if value_name not in key._store:
            raise FileNotFoundError(value_name)
        del key._store[value_name]


def test_release_version_and_notes_match_0_5_0() -> None:
    """Release metadata resolves >= 0.5.0 and matching curated release notes exist."""
    current = resolve_app_version()
    parts = tuple(int(part) for part in current.split("."))
    assert parts >= (0, 5, 0)
    releases_dir = Path(__file__).resolve().parents[1] / "docs" / "releases"
    notes_path = releases_dir / "0.5.0.md"
    assert notes_path.is_file()
    content = notes_path.read_text(encoding="utf-8")
    assert "WizConsole-Setup-0.5.0.exe" in content
    assert "WizConsole-portable-0.5.0.zip" in content
    current_notes = releases_dir / f"{current}.md"
    assert current_notes.is_file()


def test_upgrade_from_v0_4_3_migrates_data_settings_and_autostart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates launching v0.5.0 over existing v0.4.3 GestorDeLuces AppData and Run entry."""
    local_appdata = tmp_path / "LocalAppData"
    legacy_dir = local_appdata / LEGACY_APP_DATA_DIR_NAME
    legacy_dir.mkdir(parents=True)

    (legacy_dir / "bulbs.json").write_text(
        json.dumps(
            [
                {
                    "ip": "192.168.1.40",
                    "mac": "a8bb50123456",
                    "name": "Legacy Studio Bulb",
                    "module_name": "ESP01_SHRGB1C_31",
                    "is_online": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    (legacy_dir / "custom_scenes.json").write_text(
        json.dumps(
            [
                {
                    "id": "legacy01",
                    "name": "Reading Warm",
                    "mode": "temperature",
                    "brightness": 75,
                    "color": None,
                    "temperature": 3000,
                    "built_in_scene_id": None,
                    "speed": 100,
                    "is_favorite": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    (legacy_dir / "settings.json").write_text(
        json.dumps({"language": "es", "theme": "atmospheric-dark"}),
        encoding="utf-8",
    )

    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    data_dir = resolve_default_data_dir()
    assert data_dir == local_appdata / APP_DATA_DIR_NAME
    # Legacy v0.4.3 backup remains untouched on disk.
    assert (legacy_dir / "bulbs.json").is_file()

    service = LightControlService(
        controller=WizUdpController(probe_candidates=[]),
        bulb_repository=JsonBulbRepository(data_dir=data_dir),
        scene_repository=JsonSceneRepository(data_dir=data_dir),
        settings_repository=JsonSettingsRepository(data_dir=data_dir),
    )
    assert [b.name for b in service.list_bulbs()] == ["Legacy Studio Bulb"]
    assert [s.name for s in service.list_custom_scenes()] == ["Reading Warm"]
    assert service.get_language() == "es"
    assert service.get_theme() == "atmospheric-dark"
    assert service.get_auto_sync() is False
    assert service.get_favorite_builtin_scenes() == []
    assert service.get_ambilight_prefs()["min_brightness"] == 10
    assert service.get_global_hotkeys()["enabled"] is False

    # Mutate new v0.5.0 session settings and verify restart persistence.
    service.set_auto_sync(True)
    service.set_favorite_builtin_scenes([4, 12])
    service.set_global_hotkeys(True)

    restarted = LightControlService(
        controller=WizUdpController(probe_candidates=[]),
        bulb_repository=JsonBulbRepository(data_dir=data_dir),
        scene_repository=JsonSceneRepository(data_dir=data_dir),
        settings_repository=JsonSettingsRepository(data_dir=data_dir),
    )
    assert restarted.get_auto_sync() is True
    assert restarted.get_favorite_builtin_scenes() == [4, 12]
    assert restarted.get_global_hotkeys()["enabled"] is True

    # Simulate legacy HKCU Run migration from GestorDeLuces -> WizConsole.
    legacy_cmd = r'"C:\Users\Alexis\AppData\Local\Programs\GestorDeLuces.exe" --minimized'
    fake_reg = _InMemoryRegistry({LEGACY_VALUE_NAME: legacy_cmd})
    autostart = WindowsRegistryAutostart(
        registry=fake_reg,
        command_factory=lambda: (
            r'"C:\Users\Alexis\AppData\Local\Programs\WizConsole.exe" --minimized'
        ),
    )
    assert autostart.refresh_if_stale() is True
    with contextlib.suppress(KeyError):
        assert LEGACY_VALUE_NAME not in fake_reg.values
    assert DEFAULT_VALUE_NAME in fake_reg.values
    assert fake_reg.values[DEFAULT_VALUE_NAME][1].endswith("--minimized")
    registered: Any = autostart.registered_command()
    assert registered is not None and "WizConsole.exe" in registered
