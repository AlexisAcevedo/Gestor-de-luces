"""Servidor HTTP de loopback sin cache para los activos estaticos de la UI.

`webview.http.BottleServer` fija `Cache-Control` sobre `bottle.response` antes de
devolver `bottle.static_file(...)`, pero `static_file` construye un `HTTPResponse`
propio y descarta esas cabeceras. Sin cabecera `Cache-Control`, WebView2 aplica
cache heuristica sobre `127.0.0.1:42001` y sigue sirviendo versiones viejas de
`i18n.js`, `styles.css` o `js/*.js` tras una actualizacion.
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
from typing import Any

from webview import http as webview_http

LOOPBACK_HOST = "127.0.0.1"
HTTP_SERVER_THREAD_NAME = "WizConsoleHttpServer"
MAX_REQUEST_BODY_BYTES = 64 * 1024

NO_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

HTML_NO_CACHE_HEADERS: dict[str, str] = {
    **NO_CACHE_HEADERS,
    "Clear-Site-Data": '"cache"',
}

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}

HTML_CSP_HEADER = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

ASSET_HEADERS: dict[str, str] = {**NO_CACHE_HEADERS, **SECURITY_HEADERS}
HTML_ASSET_HEADERS: dict[str, str] = {
    **HTML_NO_CACHE_HEADERS,
    **SECURITY_HEADERS,
    "Content-Security-Policy": HTML_CSP_HEADER,
}


def _strip_url_suffixes(url: str) -> str:
    """Elimina fragmento `#...` y query `?v=...` al calcular la raiz estatica."""
    return url.split("#", 1)[0].split("?", 1)[0]


def _get_loopback_port() -> int:
    """Bind an ephemeral TCP port explicitly on IPv4 loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LOOPBACK_HOST, 0))
        return int(sock.getsockname()[1])


class NoCacheBottleServer(webview_http.BottleServer):
    """Variante endurecida de `BottleServer` solo-loopback y sin cache."""

    def __init__(self) -> None:
        super().__init__()
        self.uid = secrets.token_urlsafe(24)

    @classmethod
    def start_server(
        cls,
        urls: list[str],
        http_port: int | None,
        keyfile: Any = None,
        certfile: Any = None,
    ) -> tuple[str, str | None, NoCacheBottleServer]:
        from webview import _state

        apps = [u for u in urls if webview_http.is_app(u)]
        server = cls()
        bottle = webview_http.bottle
        server.port = http_port or _get_loopback_port()
        protocol = "https" if keyfile and certfile else "http"
        expected_host = f"{LOOPBACK_HOST}:{server.port}"
        expected_origin = f"{protocol}://{expected_host}"

        if apps:
            app = apps[0]
            common_path: str | None = "."
        else:
            local_urls = [_strip_url_suffixes(u) for u in urls if webview_http.is_local_url(u)]
            common_path = os.path.commonpath(local_urls) if local_urls else None
            if common_path is not None and not os.path.isdir(webview_http.abspath(common_path)):
                common_path = os.path.dirname(common_path)
            server.root_path = (
                webview_http.abspath(common_path) if common_path is not None else None
            )
            app = bottle.Bottle()

            @app.hook("before_request")
            def enforce_local_request() -> None:
                if bottle.request.method not in ("GET", "HEAD"):
                    bottle.abort(405, "Method Not Allowed")
                host_header = (bottle.request.get_header("Host") or "").strip()
                if host_header != expected_host:
                    bottle.abort(403, "Forbidden")
                origin_header = bottle.request.get_header("Origin")
                if origin_header is not None and origin_header.strip() != expected_origin:
                    bottle.abort(403, "Forbidden")
                content_length = bottle.request.get_header("Content-Length")
                if content_length is not None and content_length.strip() != "":
                    try:
                        length = int(content_length)
                    except ValueError:
                        bottle.abort(400, "Bad Request")
                    if length < 0:
                        bottle.abort(400, "Bad Request")
                    if length > MAX_REQUEST_BODY_BYTES:
                        bottle.abort(413, "Payload Too Large")

            @app.hook("after_request")
            def attach_security_headers() -> None:
                for header_name, header_value in SECURITY_HEADERS.items():
                    bottle.response.set_header(header_name, header_value)

            @app.route("/")
            @app.route("/<file:path>")
            def asset(file: str = "") -> Any:
                if not server.root_path:
                    return ""
                headers = (
                    HTML_ASSET_HEADERS
                    if file.lower().endswith((".html", ".htm"))
                    else ASSET_HEADERS
                )
                return bottle.static_file(file, root=server.root_path, headers=headers)

        server.root_path = webview_http.abspath(common_path) if common_path is not None else None
        if keyfile and certfile:
            server_adapter: Any = webview_http.SSLWSGIRefServer()
            server_adapter.host = LOOPBACK_HOST
            server_adapter.port = server.port
            server_adapter.pywebview_keyfile = keyfile
            server_adapter.pywebview_certfile = certfile
        else:
            server_adapter = webview_http.ThreadedAdapter

        server.thread = threading.Thread(
            target=lambda: bottle.run(
                app=app,
                server=server_adapter,
                host=LOOPBACK_HOST,
                port=server.port,
                quiet=not _state["debug"],
            ),
            name=HTTP_SERVER_THREAD_NAME,
            daemon=True,
        )
        server.thread.start()

        server.running = True
        server.address = f"{protocol}://{LOOPBACK_HOST}:{server.port}/"
        cls.common_path = common_path
        server.js_api_endpoint = None

        return server.address, common_path, server
