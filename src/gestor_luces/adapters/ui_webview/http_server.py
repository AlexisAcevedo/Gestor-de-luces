"""Servidor HTTP de loopback sin cache para los activos estaticos de la UI.

`webview.http.BottleServer` fija `Cache-Control` sobre `bottle.response` antes de
devolver `bottle.static_file(...)`, pero `static_file` construye un `HTTPResponse`
propio y descarta esas cabeceras. Sin cabecera `Cache-Control`, WebView2 aplica
cache heuristica sobre `127.0.0.1:42001` y sigue sirviendo versiones viejas de
`i18n.js`, `styles.css` o `js/*.js` tras una actualizacion.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from webview import http as webview_http

NO_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

HTML_NO_CACHE_HEADERS: dict[str, str] = {
    **NO_CACHE_HEADERS,
    "Clear-Site-Data": '"cache"',
}


def _strip_url_suffixes(url: str) -> str:
    """Elimina fragmento `#...` y query `?v=...` al calcular la raiz estatica."""
    return url.split("#", 1)[0].split("?", 1)[0]


class NoCacheBottleServer(webview_http.BottleServer):
    """Variante de `BottleServer` que adjunta cabeceras no-cache reales a cada activo."""

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

            @app.post(f"/js_api/{server.uid}")
            def js_api() -> str:
                bottle.response.headers["Access-Control-Allow-Origin"] = "*"
                bottle.response.headers["Access-Control-Allow-Methods"] = (
                    "PUT, GET, POST, DELETE, OPTIONS"
                )
                bottle.response.headers["Access-Control-Allow-Headers"] = (
                    "Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token"
                )
                body = json.loads(bottle.request.body.read().decode("utf-8"))
                if body["uid"] in server.js_callback:
                    return json.dumps(server.js_callback[body["uid"]](body))
                webview_http.logger.error(
                    f"JS callback function is not set for window {body['uid']}"
                )
                return ""

            @app.route("/")
            @app.route("/<file:path>")
            def asset(file: str = "") -> Any:
                if not server.root_path:
                    return ""
                headers = (
                    HTML_NO_CACHE_HEADERS
                    if file.lower().endswith((".html", ".htm"))
                    else NO_CACHE_HEADERS
                )
                return bottle.static_file(file, root=server.root_path, headers=headers)

        server.root_path = webview_http.abspath(common_path) if common_path is not None else None
        server.port = http_port or webview_http._get_random_port()
        if keyfile and certfile:
            server_adapter: Any = webview_http.SSLWSGIRefServer()
            server_adapter.port = server.port
            server_adapter.pywebview_keyfile = keyfile
            server_adapter.pywebview_certfile = certfile
        else:
            server_adapter = webview_http.ThreadedAdapter

        server.thread = threading.Thread(
            target=lambda: bottle.run(
                app=app,
                server=server_adapter,
                port=server.port,
                quiet=not _state["debug"],
            ),
            daemon=True,
        )
        server.thread.start()

        server.running = True
        protocol = "https" if keyfile and certfile else "http"
        server.address = f"{protocol}://127.0.0.1:{server.port}/"
        cls.common_path = common_path
        server.js_api_endpoint = f"{server.address}js_api/{server.uid}"

        return server.address, common_path, server
