"""Tests for the window icon assets, native menu model, autostart adapter and CLI flags."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image
import pytest

from gestor_luces.adapters.system.windows_autostart import (
    DEFAULT_VALUE_NAME,
    RUN_KEY_PATH,
    WindowsRegistryAutostart,
    build_autostart_command,
)
from gestor_luces.adapters.ui_webview.app_menu import (
    ACTION_EXIT,
    ACTION_SHOW_ABOUT,
    ACTION_SHOW_SHORTCUTS,
    ACTION_TOGGLE_AUTOSTART,
    ACTION_TOGGLE_WINDOW,
    build_about_text,
    build_app_menu,
)
from gestor_luces.main import parse_args, resolve_icon_path, resolve_png_icon_path
from gestor_luces.ports.autostart import AutostartManager
from gestor_luces.resources import resolve_asset_path


class FakeRegistry:
    """In-memory stand-in for `winreg`; never touches the real registry."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    class _Key:
        def __init__(self, path: str) -> None:
            self.path = path

        def __enter__(self) -> FakeRegistry._Key:
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

    def OpenKey(self, root: str, path: str, _res: int, _access: int) -> _Key:  # noqa: N802
        return self._Key(path)

    CreateKeyEx = OpenKey  # noqa: N815

    def QueryValueEx(self, key: _Key, name: str) -> tuple[str, int]:  # noqa: N802
        try:
            return self.values[(key.path, name)], self.REG_SZ
        except KeyError:
            raise FileNotFoundError(name) from None

    def SetValueEx(self, key: _Key, name: str, _res: int, _kind: int, value: str) -> None:  # noqa: N802
        self.values[(key.path, name)] = value

    def DeleteValue(self, key: _Key, name: str) -> None:  # noqa: N802
        try:
            del self.values[(key.path, name)]
        except KeyError:
            raise FileNotFoundError(name) from None


def test_parse_args_minimized_flag() -> None:
    assert parse_args([]).minimized is False
    assert parse_args(["--minimized"]).minimized is True
    args = parse_args(["--minimized", "--debug"])
    assert args.minimized and args.debug


def test_icon_assets_exist_and_ico_has_all_sizes() -> None:
    assert resolve_icon_path().is_file()
    assert resolve_png_icon_path().is_file()
    assert resolve_asset_path("icon", "app.ico") == resolve_icon_path()
    with Image.open(resolve_icon_path()) as ico:
        assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(ico.info["sizes"])


def test_app_menu_structure_and_actions() -> None:
    menus = build_app_menu(language="en", window_visible=True, autostart_enabled=True)
    assert [m.title for m in menus] == ["File", "Help"]
    file_items = menus[0].items
    assert [i.action_id for i in file_items] == [
        ACTION_TOGGLE_WINDOW,
        ACTION_TOGGLE_AUTOSTART,
        "",
        ACTION_EXIT,
    ]
    assert file_items[0].label == "Hide window"
    assert file_items[1].checked is True
    assert file_items[2].is_separator
    assert [i.action_id for i in menus[1].items] == [ACTION_SHOW_SHORTCUTS, ACTION_SHOW_ABOUT]


def test_app_menu_labels_follow_language_and_state() -> None:
    es = build_app_menu(language="es", window_visible=False, autostart_enabled=False)
    assert [m.title for m in es] == ["Archivo", "Ayuda"]
    assert es[0].items[0].label == "Mostrar ventana"
    assert es[0].items[1].label == "Iniciar con Windows"
    assert es[0].items[1].checked is False
    assert es[0].items[3].label == "Salir"
    fallback = build_app_menu(language="fr")
    assert fallback[0].title == "File"


def test_about_text_contains_version_and_license() -> None:
    text = build_about_text("en", "1.2.3", "MIT")
    assert "1.2.3" in text and "MIT" in text
    assert "Versión" in build_about_text("es", "1.2.3")


def test_build_autostart_command_always_minimized() -> None:
    frozen = build_autostart_command(frozen=True, executable=r"C:\Apps\GestorDeLuces.exe")
    assert frozen == r'"C:\Apps\GestorDeLuces.exe" --minimized'
    dev = build_autostart_command(frozen=False, executable=r"C:\Nope\python.exe")
    assert dev.endswith("-m gestor_luces.main --minimized")


def test_autostart_adapter_enable_disable_with_fake_registry() -> None:
    registry = FakeRegistry()
    autostart = WindowsRegistryAutostart(registry=registry, command_factory=lambda: "cmd --minimized")
    assert isinstance(autostart, AutostartManager)
    assert autostart.is_enabled() is False
    autostart.disable()  # missing entry is not an error
    autostart.enable()
    assert autostart.is_enabled() is True
    assert registry.values[(RUN_KEY_PATH, DEFAULT_VALUE_NAME)] == "cmd --minimized"
    autostart.disable()
    assert autostart.is_enabled() is False


def test_autostart_refreshes_stale_path_only_when_enabled() -> None:
    registry = FakeRegistry()
    command = {"value": r'"C:\Old\app.exe" --minimized'}
    autostart = WindowsRegistryAutostart(registry=registry, command_factory=lambda: command["value"])
    assert autostart.refresh_if_stale() is False  # disabled: never creates an entry
    assert autostart.is_enabled() is False
    autostart.enable()
    assert autostart.refresh_if_stale() is False  # up to date
    command["value"] = r'"D:\New\app.exe" --minimized'
    assert autostart.refresh_if_stale() is True
    assert autostart.registered_command() == r'"D:\New\app.exe" --minimized'


def test_bridge_autostart_methods(tmp_path: Path) -> None:
    from gestor_luces.main import build_application

    registry = FakeRegistry()
    autostart = WindowsRegistryAutostart(registry=registry, command_factory=lambda: "cmd --minimized")
    _, bridge = build_application(data_dir=tmp_path, autostart=autostart)
    changes: list[int] = []
    bridge.set_state_change_listener(lambda: changes.append(1))
    try:
        assert bridge.get_autostart() == {"ok": True, "enabled": False}
        assert bridge.set_autostart(True) == {"ok": True, "enabled": True}
        assert bridge.get_autostart()["enabled"] is True
        assert bridge.set_autostart(False)["enabled"] is False
        assert len(changes) == 2
    finally:
        bridge.shutdown()


@pytest.mark.parametrize("method", ["get_autostart", "set_autostart"])
def test_bridge_without_autostart_reports_unavailable(tmp_path: Path, method: str) -> None:
    from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
    from gestor_luces.main import build_application

    service, bridge = build_application(data_dir=tmp_path, autostart=None)
    bridge.shutdown()
    plain = WebviewBridge(service=service)
    try:
        result = getattr(plain, method)(True) if method == "set_autostart" else plain.get_autostart()
        assert result["ok"] is False
    finally:
        plain.shutdown()
