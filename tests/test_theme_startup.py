"""Regression tests for pre-paint theme bootstrap and URL fragment handoff."""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urljoin

import pytest
import webview.util

from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService
from gestor_luces.desktop.app import DesktopApplication, _build_initial_ui_url
from gestor_luces.main import _ui_asset_paths, resolve_ui_directory


class _FakeEvent:
    def __iadd__(self, _handler: object) -> _FakeEvent:
        return self


class _FakeWindowEvents:
    def __init__(self) -> None:
        self.shown = _FakeEvent()
        self.closing = _FakeEvent()
        self.minimized = _FakeEvent()
        self.closed = _FakeEvent()


class _FakeWebviewModule:
    def __init__(self) -> None:
        self.screens = [SimpleNamespace(width=1920, height=1080)]
        self.create_window_calls: list[dict[str, Any]] = []

    def create_window(self, **kwargs: Any) -> SimpleNamespace:
        self.create_window_calls.append(kwargs)
        return SimpleNamespace(events=_FakeWindowEvents())


class _StaticThemeService(LightControlService):
    def __init__(self, theme: str) -> None:
        super().__init__(controller=WizUdpController(probe_candidates=[]))
        self._theme = theme

    def get_theme(self) -> str:
        return self._theme


@pytest.mark.parametrize(
    ("raw_theme", "expected_theme"),
    [
        ("atmospheric-dark", "atmospheric-dark"),
        ("  Atmospheric-Dark ", "atmospheric-dark"),
        ("architectural-stone", "architectural-stone"),
        ("unknown-theme", "architectural-stone"),
    ],
)
def test_build_initial_ui_url_normalizes_theme_fragment(
    tmp_path: Path, raw_theme: str, expected_theme: str
) -> None:
    index_path = tmp_path / "ui" / "index.html"
    url = _build_initial_ui_url(index_path, raw_theme)
    assert url == f"{index_path}#theme={expected_theme}"


@pytest.mark.parametrize(
    ("theme", "expected_bg"),
    [
        ("atmospheric-dark", "#08090C"),
        ("architectural-stone", "#F4F1EA"),
    ],
)
def test_create_window_passes_theme_fragment_and_background_color(
    tmp_path: Path, theme: str, expected_bg: str
) -> None:
    ui_dir = tmp_path / "ui"
    index_path = ui_dir / "index.html"
    service = _StaticThemeService(theme)
    bridge = WebviewBridge(service=service)
    fake_webview = _FakeWebviewModule()
    app = DesktopApplication(
        service=service,
        bridge=bridge,
        index_path=index_path,
        icon_path=tmp_path / "app.ico",
        ui_dir=ui_dir,
        webview_module=fake_webview,
    )
    try:
        app.create_window()
    finally:
        bridge.shutdown()

    assert len(fake_webview.create_window_calls) == 1
    call = fake_webview.create_window_calls[0]
    assert call["url"] == f"{index_path}#theme={theme}"
    assert call["background_color"] == expected_bg


def test_initial_ui_url_preserves_fragment_through_pywebview_url_resolution() -> None:
    ui_dir = resolve_ui_directory()
    index_path = ui_dir / "index.html"
    url = _build_initial_ui_url(index_path, "atmospheric-dark")

    assert webview.util.is_local_url(url) is True
    base_file = url.split("#", 1)[0]
    common_path = os.path.dirname(os.path.commonpath([base_file]))
    rel = os.path.relpath(url, common_path)
    resolved = urljoin("http://127.0.0.1:42001/", rel.replace(os.sep, "/"))
    assert resolved == "http://127.0.0.1:42001/index.html#theme=atmospheric-dark"


def test_index_html_loads_theme_boot_synchronously_before_css_under_strict_csp() -> None:
    ui_dir = resolve_ui_directory()
    assets = _ui_asset_paths(ui_dir)
    assert assets["theme_boot"] == ui_dir / "js" / "theme-boot.js"
    assert assets["theme_boot"].is_file()

    index_html = assets["index"].read_text(encoding="utf-8")
    head_match = re.search(r"<head>(.*?)</head>", index_html, flags=re.DOTALL | re.IGNORECASE)
    assert head_match is not None
    head_html = head_match.group(1)

    boot_tag = '<script src="js/theme-boot.js"></script>'
    themes_link = '<link rel="stylesheet" href="themes.css">'
    assert boot_tag in head_html
    assert themes_link in head_html
    assert head_html.index(boot_tag) < head_html.index(themes_link)

    assert "unsafe-inline" not in index_html.lower()
    inline_scripts = re.findall(
        r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
        index_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert inline_scripts == []
