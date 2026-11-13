"""Publica el porcentaje de cobertura como endpoint JSON de shields.io.

`PLAN.md` T-6.6: el numero de cobertura del README no se escribe a mano, porque un numero
escrito a mano envejece en silencio. El CI mide, el gate por paquete
(`scripts/check_coverage.py`) decide si el numero es aceptable, y este script traduce el
reporte de `pytest-cov` a la forma que shields.io sabe leer:

    {"schemaVersion": 1, "label": "coverage", "message": "84.2%", "color": "green"}

El archivo se publica en una rama aparte y el README lo muestra con
`https://img.shields.io/endpoint?url=...`. El color se calcula sobre el mismo numero
redondeado que se muestra (>= 80 verde, >= 60 amarillo, resto rojo), asi que el color y el
texto del badge nunca se contradicen.

Uso: `python scripts/coverage_badge_json.py --output badge-out/coverage.json [coverage.json]`
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: Nombre por defecto del reporte que produce `pytest-cov --cov-report=json:<ruta>`.
DEFAULT_REPORT_PATH = "coverage.json"

#: Etiqueta fija del badge, a la izquierda del numero.
BADGE_LABEL = "coverage"

#: Piso de verde y piso de amarillo, aplicados sobre el porcentaje ya redondeado.
GREEN_FLOOR = 80.0
YELLOW_FLOOR = 60.0


class CoverageReportError(Exception):
    """El reporte no existe, no es JSON valido o no trae `totals.percent_covered`."""


def badge_color(percent: float) -> str:
    """Color de shields.io para un porcentaje ya redondeado."""
    if percent >= GREEN_FLOOR:
        return "green"
    if percent >= YELLOW_FLOOR:
        return "yellow"
    return "red"


def badge_payload(total_percent: float) -> dict[str, object]:
    """Endpoint JSON de shields.io para un porcentaje de cobertura total."""
    percent = round(total_percent, 1)
    return {
        "schemaVersion": 1,
        "label": BADGE_LABEL,
        "message": f"{percent:.1f}%",
        "color": badge_color(percent),
    }


def read_total_percent(report_path: Path) -> float:
    """Extrae `totals.percent_covered` del reporte JSON de `pytest-cov`."""
    if not report_path.is_file():
        raise CoverageReportError(f"coverage report not found: {report_path}")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CoverageReportError(f"cannot read coverage report {report_path}: {exc}") from exc
    totals = report.get("totals") if isinstance(report, dict) else None
    percent = totals.get("percent_covered") if isinstance(totals, dict) else None
    if isinstance(percent, bool) or not isinstance(percent, int | float):
        raise CoverageReportError(f"coverage report has no totals.percent_covered: {report_path}")
    return float(percent)


def render(payload: dict[str, object]) -> str:
    """Serializa el endpoint JSON tal como se escribe en disco."""
    return json.dumps(payload, indent=2) + "\n"


def write_badge(report_path: Path, output_path: Path) -> dict[str, object]:
    """Escribe el endpoint JSON del reporte y devuelve el payload publicado."""
    payload = badge_payload(read_total_percent(report_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render(payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    """CLI: 0 si escribio el badge, 2 si el reporte no sirve para publicarlo."""
    parser = argparse.ArgumentParser(
        description="Publish the total coverage percentage as a shields.io endpoint JSON."
    )
    parser.add_argument(
        "report",
        nargs="?",
        default=DEFAULT_REPORT_PATH,
        help=f"coverage JSON produced by pytest-cov (default: {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="path of the endpoint JSON to write",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        payload = write_badge(Path(args.report), Path(args.output))
    except CoverageReportError as exc:
        print(f"coverage badge: {exc}", file=sys.stderr)
        return 2
    print(render(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
