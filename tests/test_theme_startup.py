"""Regression tests for pre-paint theme bootstrap and URL fragment handoff."""

from __future__ import annotations

import http.client
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urljoin

import pytest
import webview.util

from wiz_console.adapters.ui_webview.bridge import BlockedJsApi, WebviewBridge
from wiz_console.adapters.ui_webview.dispatch import JS_API_DISPATCH
from wiz_console.adapters.ui_webview.http_server import NoCacheBottleServer
from wiz_console.adapters.wiz.udp_controller import WizUdpController
from wiz_console.application.service import LightControlService
from wiz_console.desktop import app as desktop_app
from wiz_console.desktop.app import DesktopApplication, _build_initial_ui_url
from wiz_console.main import _ui_asset_paths, resolve_ui_directory


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
        self.exposed_functions: list[tuple[Any, ...]] = []

    def create_window(self, **kwargs: Any) -> SimpleNamespace:
        self.create_window_calls.append(kwargs)
        exposed_store = self.exposed_functions
        return SimpleNamespace(
            events=_FakeWindowEvents(),
            expose=lambda *funcs: exposed_store.append(funcs),
        )


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
    assert _build_initial_ui_url(index_path, raw_theme) == f"{index_path}#theme={expected_theme}"
    assert (
        _build_initial_ui_url(index_path, raw_theme, cache_bust="boot123")
        == f"{index_path}?v=boot123#theme={expected_theme}"
    )


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
    assert call["url"].startswith(f"{index_path}?v=")
    assert call["url"].endswith(f"#theme={theme}&lang=en")
    assert call["background_color"] == expected_bg
    assert isinstance(call["js_api"], BlockedJsApi)
    assert len(fake_webview.exposed_functions) == 1
    assert len(fake_webview.exposed_functions[0]) == len(JS_API_DISPATCH) + 1


def test_desktop_application_start_uses_no_cache_http_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desktop_app, "resolve_default_data_dir", lambda: tmp_path)
    monkeypatch.setattr(desktop_app, "create_tray_view", lambda _dispatch: None)

    start_calls: list[dict[str, Any]] = []
    fake_webview = _FakeWebviewModule()
    fake_webview.start = lambda **kwargs: start_calls.append(kwargs)  # type: ignore[attr-defined]

    service = _StaticThemeService("atmospheric-dark")
    bridge = WebviewBridge(service=service)
    app = DesktopApplication(
        service=service,
        bridge=bridge,
        index_path=tmp_path / "index.html",
        icon_path=tmp_path / "app.ico",
        ui_dir=tmp_path,
        webview_module=fake_webview,
    )
    app.create_window()
    app.start()

    assert len(start_calls) == 1
    assert start_calls[0]["http_server"] is True
    assert start_calls[0]["server"] is NoCacheBottleServer


def test_no_cache_bottle_server_emits_real_cache_headers_and_blocks_traversal() -> None:
    ui_dir = resolve_ui_directory()
    initial_url = _build_initial_ui_url(
        ui_dir / "index.html",
        "atmospheric-dark",
        cache_bust="boot123",
    )
    _addr, common_path, srv = NoCacheBottleServer.start_server([initial_url], http_port=None)
    assert Path(common_path or "").resolve() == ui_dir.resolve()

    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=3)
    try:
        conn.request("GET", "/index.html?v=boot123")
        html_resp = conn.getresponse()
        html_body = html_resp.read().decode("utf-8")
        assert html_resp.status == 200
        assert html_resp.getheader("Cache-Control") == "no-store, no-cache, must-revalidate"
        assert html_resp.getheader("Pragma") == "no-cache"
        assert html_resp.getheader("Expires") == "0"
        assert html_resp.getheader("Clear-Site-Data") == '"cache"'
        assert 'src="js/theme-boot.js"' in html_body

        conn.request("GET", "/i18n.js")
        js_resp = conn.getresponse()
        js_body = js_resp.read().decode("utf-8")
        assert js_resp.status == 200
        assert js_resp.getheader("Cache-Control") == "no-store, no-cache, must-revalidate"
        assert js_resp.getheader("Clear-Site-Data") is None
        assert '"theme.stoneShort": "Claro"' in js_body
        assert '"theme.stoneShort": "Light"' in js_body

        conn.request("GET", "/../../pyproject.toml")
        traversal_resp = conn.getresponse()
        traversal_resp.read()
        assert traversal_resp.status in (403, 404)
    finally:
        conn.close()


def test_no_cache_bottle_server_hardens_loopback_and_headers() -> None:
    import uuid

    ui_dir = resolve_ui_directory()
    initial_url = _build_initial_ui_url(
        ui_dir / "index.html",
        "atmospheric-dark",
        cache_bust="boot123",
    )
    addr, _common_path, srv = NoCacheBottleServer.start_server([initial_url], http_port=None)
    assert addr.startswith("http://127.0.0.1:")
    assert srv.js_api_endpoint is None
    with pytest.raises(ValueError):
        uuid.UUID(srv.uid)

    expected_origin = f"http://127.0.0.1:{srv.port}"

    def request(
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
    ) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=3)
        try:
            conn.request(method, path, headers=headers or {})
            resp = conn.getresponse()
            resp.read()
            return resp
        finally:
            conn.close()

    html_resp = request("GET", "/index.html?v=boot123", headers={"Origin": expected_origin})
    assert html_resp.status == 200
    assert html_resp.getheader("X-Content-Type-Options") == "nosniff"
    assert html_resp.getheader("X-Frame-Options") == "DENY"
    assert html_resp.getheader("Referrer-Policy") == "no-referrer"
    assert html_resp.getheader("Cross-Origin-Resource-Policy") == "same-origin"
    assert html_resp.getheader("Access-Control-Allow-Origin") is None
    csp = html_resp.getheader("Content-Security-Policy") or ""
    assert "frame-ancestors 'none'" in csp

    js_resp = request("GET", "/i18n.js")
    assert js_resp.status == 200
    assert js_resp.getheader("X-Content-Type-Options") == "nosniff"
    assert js_resp.getheader("X-Frame-Options") == "DENY"
    assert js_resp.getheader("Access-Control-Allow-Origin") is None

    for bad_host in ("evil.example", "127.0.0.1:1"):
        host_resp = request("GET", "/index.html", headers={"Host": bad_host})
        assert host_resp.status == 403
        assert host_resp.getheader("X-Content-Type-Options") == "nosniff"

    origin_resp = request("GET", "/index.html", headers={"Origin": "https://evil.example"})
    assert origin_resp.status == 403
    assert origin_resp.getheader("Access-Control-Allow-Origin") is None

    for method, path in (("POST", f"/js_api/{srv.uid}"), ("OPTIONS", "/index.html")):
        method_resp = request(method, path)
        assert method_resp.status == 405
        assert method_resp.getheader("Access-Control-Allow-Origin") is None

    large_resp = request("GET", "/index.html", headers={"Content-Length": str(128 * 1024)})
    assert large_resp.status == 413

    for bad_len in ("not-a-number", "-1"):
        bad_len_resp = request("GET", "/index.html", headers={"Content-Length": bad_len})
        assert bad_len_resp.status == 400

    missing_resp = request("GET", "/does-not-exist.js")
    assert missing_resp.status == 404
    assert missing_resp.getheader("X-Content-Type-Options") == "nosniff"


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


def test_build_initial_ui_url_supports_language_fragment(tmp_path: Path) -> None:
    index_path = tmp_path / "ui" / "index.html"
    assert (
        _build_initial_ui_url(index_path, "atmospheric-dark", language="es")
        == f"{index_path}#theme=atmospheric-dark&lang=es"
    )
    assert (
        _build_initial_ui_url(index_path, "architectural-stone", language="fr", cache_bust="x1")
        == f"{index_path}?v=x1#theme=architectural-stone&lang=en"
    )


def test_desktop_application_localizes_window_title_on_boot_and_language_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wiz_console.adapters.storage.json_repositories import JsonSettingsRepository
    from wiz_console.adapters.ui_webview.app_menu import APP_DISPLAY_NAME, APP_DISPLAY_NAME_ES

    set_title_calls: list[str] = []
    menu_theme_calls: list[str] = []
    monkeypatch.setattr(
        desktop_app, "_set_windows_dark_titlebar_attribute", lambda *_a, **_kw: True
    )
    monkeypatch.setattr(
        desktop_app,
        "_sync_native_menu_theme",
        lambda _win, theme: menu_theme_calls.append(theme) or True,
    )

    settings_repo = JsonSettingsRepository(data_dir=tmp_path)
    settings_repo.save_settings({"language": "es", "theme": "atmospheric-dark"})
    service = LightControlService(
        controller=WizUdpController(probe_candidates=[]),
        settings_repository=settings_repo,
    )
    bridge = WebviewBridge(service=service)
    fake_webview = _FakeWebviewModule()
    orig_create = fake_webview.create_window

    def _create_with_set_title(**kwargs: Any) -> SimpleNamespace:
        win = orig_create(**kwargs)
        win.set_title = lambda title: set_title_calls.append(title)
        return win

    fake_webview.create_window = _create_with_set_title  # type: ignore[method-assign]
    app = DesktopApplication(
        service=service,
        bridge=bridge,
        index_path=tmp_path / "index.html",
        icon_path=tmp_path / "app.ico",
        ui_dir=tmp_path,
        webview_module=fake_webview,
    )
    try:
        app.create_window()
        assert fake_webview.create_window_calls[0]["title"] == APP_DISPLAY_NAME_ES
        assert fake_webview.create_window_calls[0]["url"].endswith(
            "#theme=atmospheric-dark&lang=es"
        )

        service.set_language("en")
        app.on_state_changed()
        assert set_title_calls == [APP_DISPLAY_NAME]
        assert menu_theme_calls == ["atmospheric-dark"]

        service.set_theme("architectural-stone")
        app.on_state_changed()
        assert menu_theme_calls == ["atmospheric-dark", "architectural-stone"]
    finally:
        bridge.shutdown()


def test_hide_to_tray_notice_shows_once_and_persists_across_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wiz_console.adapters.storage.json_repositories import JsonSettingsRepository

    monkeypatch.setattr(
        desktop_app, "_set_windows_dark_titlebar_attribute", lambda *_a, **_kw: True
    )
    monkeypatch.setattr(desktop_app, "_sync_native_menu_theme", lambda *_a, **_kw: False)

    notifications: list[tuple[str, str]] = []
    settings_repo = JsonSettingsRepository(data_dir=tmp_path)
    settings_repo.save_settings({"language": "es", "theme": "architectural-stone"})
    service = LightControlService(
        controller=WizUdpController(probe_candidates=[]),
        settings_repository=settings_repo,
    )
    bridge = WebviewBridge(service=service)
    fake_webview = _FakeWebviewModule()

    def _create_with_hide(**kwargs: Any) -> SimpleNamespace:
        win = _FakeWebviewModule.create_window(fake_webview, **kwargs)
        win.hide = lambda: None
        return win

    fake_webview.create_window = _create_with_hide  # type: ignore[method-assign]
    app = DesktopApplication(
        service=service,
        bridge=bridge,
        index_path=tmp_path / "index.html",
        icon_path=tmp_path / "app.ico",
        ui_dir=tmp_path,
        webview_module=fake_webview,
    )

    def _record_notification(title: str, msg: str) -> bool:
        notifications.append((title, msg))
        return True

    try:
        app.create_window()
        assert app.tray is not None
        app.tray.show_notification = _record_notification  # type: ignore[method-assign]

        # First user close/minimize hide sends localized Spanish notice and persists flag
        app._apply_hide(show_tray_hint=True)
        assert len(notifications) == 1
        assert "Consola de Iluminación WiZ" in notifications[0][0]
        assert "bandeja" in notifications[0][1]
        assert settings_repo.load_settings()["tray_hint_seen"] is True

        # Second hide on the same instance must NOT notify again
        app._apply_hide(show_tray_hint=True)
        assert len(notifications) == 1
    finally:
        bridge.shutdown()

    # Fresh instance reloading persisted settings must also suppress repeated notices
    reloaded_service = LightControlService(
        controller=WizUdpController(probe_candidates=[]),
        settings_repository=JsonSettingsRepository(data_dir=tmp_path),
    )
    assert reloaded_service.get_tray_hint_seen() is True
    reloaded_bridge = WebviewBridge(service=reloaded_service)
    app2 = DesktopApplication(
        service=reloaded_service,
        bridge=reloaded_bridge,
        index_path=tmp_path / "index.html",
        icon_path=tmp_path / "app.ico",
        ui_dir=tmp_path,
        webview_module=fake_webview,
    )
    try:
        app2.create_window()
        assert app2.tray is not None
        app2.tray.show_notification = _record_notification  # type: ignore[method-assign]
        app2._apply_hide(show_tray_hint=True)
        assert len(notifications) == 1
    finally:
        reloaded_bridge.shutdown()
