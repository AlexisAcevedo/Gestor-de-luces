"""Raiz de composicion (Composition Root) de la aplicacion de escritorio.

Este modulo ensambla las capas de la Arquitectura Hexagonal inyectando las
implementaciones concretas de infraestructura (`WizUdpController`) en los casos
de uso (`LightControlService`) y exponiendolos al adaptador primario de ventana
nativa (`WebviewBridge` + `pywebview`).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from gestor_luces.adapters.ui_webview.bridge import WebviewBridge
from gestor_luces.adapters.wiz.udp_controller import WizUdpController
from gestor_luces.application.service import LightControlService


def resolve_ui_directory() -> Path:
    """Localiza el directorio `ui/` relativo a la raiz del proyecto."""
    return Path(__file__).resolve().parents[2] / "ui"


def build_application() -> tuple[LightControlService, WebviewBridge]:
    """Instancia y conecta el controlador UDP, el servicio de aplicacion y el puente JS."""
    controller = WizUdpController()
    service = LightControlService(controller=controller)
    bridge = WebviewBridge(service=service)
    return service, bridge


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Procesa los argumentos de linea de comandos para ejecucion normal o smoke test."""
    parser = argparse.ArgumentParser(
        prog="gestor-luces",
        description="WiZ Architectural Lighting Console desktop application.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable pywebview inspector and developer tools.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Verify composition root and UI assets without opening the native GUI loop.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada principal de la aplicacion de escritorio."""
    args = parse_args(argv)
    ui_dir = resolve_ui_directory()
    index_path = ui_dir / "index.html"
    styles_path = ui_dir / "styles.css"
    script_path = ui_dir / "app.js"

    _, bridge = build_application()

    if args.smoke_test:
        try:
            missing = [
                str(p)
                for p in (index_path, styles_path, script_path)
                if not p.is_file()
            ]
            if missing:
                print(f"Smoke test failed: missing UI assets: {missing}", file=sys.stderr)
                return 1
            print(f"Composition root initialized. UI entry verified at: {index_path}")
            return 0
        finally:
            bridge.shutdown()

    import webview

    window = webview.create_window(
        title="WiZ Architectural Lighting Console",
        url=index_path.as_uri(),
        js_api=bridge,
        width=1180,
        height=780,
        min_size=(920, 620),
        background_color="#0D0F12",
    )
    window.events.closed += bridge.shutdown
    webview.start(debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
