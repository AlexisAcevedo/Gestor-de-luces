"""Opt-in loopback-only local HTTP API server for LAN scripting and Stream Deck integration."""

from __future__ import annotations

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_LOGGER = logging.getLogger(__name__)

LOCAL_API_THREAD_NAME = "WizConsoleLocalApi"
MAX_BODY_BYTES = 16 * 1024


class LocalHttpApiServer:
    """Loopback (`127.0.0.1`) Bearer-authenticated HTTP server dispatching to `WebviewBridge`."""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port: int | None = None
        self._token: str = ""

    @property
    def port(self) -> int | None:
        """Active bound TCP port on `127.0.0.1` (None when stopped)."""
        with self._lock:
            return self._port

    @property
    def is_running(self) -> bool:
        """Return True while the loopback HTTP listener thread is alive."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, *, port: int, token: str) -> int:
        """Bind `127.0.0.1:port` on a single daemon thread or update token in place."""
        cleaned_token = str(token or "").strip()
        if not cleaned_token:
            raise ValueError("Local HTTP API requires a non-empty Bearer token.")
        with self._lock:
            self._token = cleaned_token
            if (
                self._server is not None
                and self._thread is not None
                and self._thread.is_alive()
                and self._port == port
            ):
                return self._port

        self.stop()

        owner = self

        class _ApiHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                _LOGGER.debug("LocalAPI %s", format % args)

            def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
                encoded = json.dumps(payload).encode("utf-8")
                if status_code >= 400:
                    self.close_connection = True
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)

            def _check_auth(self) -> bool:
                with owner._lock:
                    expected = owner._token
                if not expected:
                    self._send_json(401, {"ok": False, "error": "Unauthorized"})
                    return False
                auth_header = self.headers.get("Authorization", "")
                prefix = "Bearer "
                if not auth_header.startswith(prefix):
                    self._send_json(401, {"ok": False, "error": "Missing Bearer token"})
                    return False
                provided = auth_header[len(prefix) :].strip()
                if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
                    self._send_json(401, {"ok": False, "error": "Invalid Bearer token"})
                    return False
                return True

            def _read_json_body(self) -> dict[str, Any] | None:
                raw_len = self.headers.get("Content-Length", "0")
                try:
                    length = int(raw_len)
                except ValueError:
                    self._send_json(400, {"ok": False, "error": "Invalid Content-Length"})
                    return None
                if length < 0 or length > MAX_BODY_BYTES:
                    self._send_json(413, {"ok": False, "error": "Payload exceeds 16 KiB limit"})
                    return None
                if length == 0:
                    return {}
                raw_bytes = self.rfile.read(length)
                try:
                    parsed = json.loads(raw_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json(400, {"ok": False, "error": "Malformed JSON body"})
                    return None
                if not isinstance(parsed, dict):
                    self._send_json(400, {"ok": False, "error": "Expected JSON object"})
                    return None
                return parsed

            def do_GET(self) -> None:
                if not self._check_auth():
                    return
                if self.path != "/api/v1/status":
                    self._send_json(404, {"ok": False, "error": "Not found"})
                    return
                snapshot = owner._bridge.get_initial_state()
                sanitized = {
                    "ok": bool(snapshot.get("ok", True)),
                    "bulbs": snapshot.get("bulbs", []),
                    "selected_ips": snapshot.get("selected_ips", []),
                    "zones": snapshot.get("zones", []),
                    "custom_scenes": snapshot.get("custom_scenes", []),
                    "ambilight": snapshot.get("ambilight", {}),
                    "music_sync": snapshot.get("music_sync", {}),
                    "sleep_timer": snapshot.get("sleep_timer", {}),
                }
                self._send_json(200 if sanitized["ok"] else 400, sanitized)

            def do_POST(self) -> None:
                if not self._check_auth():
                    return
                body = self._read_json_body()
                if body is None:
                    return
                result: dict[str, Any] | None = None
                try:
                    if self.path == "/api/v1/power":
                        result = owner._bridge.set_power(
                            bool(body.get("is_on")),
                            body.get("brightness"),
                            body.get("ips"),
                        )
                    elif self.path == "/api/v1/brightness":
                        result = owner._bridge.set_brightness(
                            body.get("brightness"),
                            body.get("ips"),
                        )
                    elif self.path == "/api/v1/color":
                        result = owner._bridge.set_color(
                            body.get("r"),
                            body.get("g"),
                            body.get("b"),
                            body.get("brightness"),
                            body.get("ips"),
                        )
                    elif self.path == "/api/v1/temperature":
                        result = owner._bridge.set_temperature(
                            body.get("kelvin"),
                            body.get("brightness"),
                            body.get("ips"),
                        )
                    elif self.path == "/api/v1/scene":
                        result = owner._bridge.set_builtin_scene(
                            body.get("scene_id"),
                            body.get("speed"),
                            body.get("brightness"),
                            body.get("ips"),
                        )
                    elif self.path == "/api/v1/preset":
                        result = owner._bridge.apply_custom_scene(
                            body.get("scene_id"),
                            body.get("ips"),
                        )
                except (TypeError, ValueError) as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if result is None:
                    self._send_json(404, {"ok": False, "error": "Not found"})
                    return
                code = 200 if result.get("ok") else 400
                self._send_json(
                    code,
                    {
                        "ok": bool(result.get("ok")),
                        "error": result.get("error"),
                        "bulbs": result.get("bulbs", []),
                    },
                )

        server = ThreadingHTTPServer(("127.0.0.1", port), _ApiHandler)
        server.daemon_threads = True
        server.allow_reuse_address = True
        bound_port = int(server.server_address[1])
        thread = threading.Thread(
            target=server.serve_forever,
            name=LOCAL_API_THREAD_NAME,
            daemon=True,
        )
        with self._lock:
            self._server = server
            self._thread = thread
            self._port = bound_port
            self._token = cleaned_token
        thread.start()
        return bound_port

    def stop(self) -> None:
        """Shut down the HTTP listener and join its daemon thread cleanly."""
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._port = None

        if server is not None:
            try:
                server.shutdown()
            except Exception:
                _LOGGER.debug("Ignoring LocalHttpApiServer shutdown error.", exc_info=True)
            try:
                server.server_close()
            except Exception:
                _LOGGER.debug("Ignoring LocalHttpApiServer close error.", exc_info=True)

        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2.0)
