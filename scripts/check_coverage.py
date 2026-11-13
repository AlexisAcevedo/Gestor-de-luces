"""Falla el job de CI cuando un paquete de `gestor_luces` baja de su umbral de cobertura.

`PLAN.md` T-6.6: un porcentaje global se puede maquillar (subir el total agregando tests
triviales en una capa y dejar otra sin probar), asi que los umbrales son **por paquete**:

- `domain` 90: reglas puras, sin E/S, donde el costo de un test es nulo.
- `application` 75: casos de uso con colaboradores inyectados.
- `adapters` 55: adaptadores con hardware y toolkit grafico imposibles de ejercitar headless.

`ports` y `desktop` se informan pero no se gatean: el primero es contrato (`Protocol`) y el
segundo es cableado de composicion.

Uso: `python scripts/check_coverage.py [coverage.json]`
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

#: Cobertura minima de lineas por paquete (ver el encabezado del modulo).
PACKAGE_THRESHOLDS: dict[str, float] = {
    "domain": 90.0,
    "application": 75.0,
    "adapters": 55.0,
}

#: Paquetes que solo se informan: contrato sin logica y cableado de composicion.
REPORT_ONLY_PACKAGES = frozenset({"ports", "desktop"})

#: Clave con la que se agrupan los modulos sueltos de `src/gestor_luces/` (main, cli, ...).
TOP_LEVEL_KEY = "(top-level)"

_SOURCE_MARKER = "gestor_luces/"


def package_key(path: str) -> str:
    """Devuelve el paquete de `src/gestor_luces/` al que pertenece un archivo del reporte."""
    normalized = path.replace("\\", "/")
    if _SOURCE_MARKER not in normalized:
        return TOP_LEVEL_KEY
    relative = normalized.split(_SOURCE_MARKER, 1)[1]
    parts = relative.split("/")
    return parts[0] if len(parts) > 1 else TOP_LEVEL_KEY


def package_coverages(files: Mapping[str, Mapping[str, object]]) -> dict[str, tuple[int, int]]:
    """Agrupa las lineas cubiertas y totales de un reporte JSON de coverage por paquete."""
    totals: dict[str, list[int]] = {}
    for path, entry in files.items():
        summary = entry.get("summary") if isinstance(entry, Mapping) else None
        if not isinstance(summary, Mapping):
            continue
        key = package_key(path)
        covered = int(summary.get("covered_lines", 0))  # type: ignore[arg-type]
        statements = int(summary.get("num_statements", 0))  # type: ignore[arg-type]
        bucket = totals.setdefault(key, [0, 0])
        bucket[0] += covered
        bucket[1] += statements
    return {key: (covered, total) for key, (covered, total) in totals.items()}


def find_violations(coverages: Mapping[str, tuple[int, int]]) -> list[str]:
    """Devuelve un mensaje por paquete obligatorio ausente o por debajo de su umbral."""
    violations: list[str] = []
    for package, threshold in PACKAGE_THRESHOLDS.items():
        if package not in coverages:
            violations.append(
                f"{package}: missing from the coverage report (needs >= {threshold:g}%)"
            )
            continue
        covered, total = coverages[package]
        percent = 100.0 * covered / total if total else 0.0
        if percent < threshold:
            violations.append(
                f"{package}: {percent:.1f}% of {total} lines is below the {threshold:g}% floor"
            )
    return violations


def render_table(coverages: Mapping[str, tuple[int, int]]) -> str:
    """Tabla legible: cobertura por paquete, umbral aplicado y veredicto."""
    lines = [f"{'package':12s} {'lines':>13s} {'cover':>7s} {'floor':>7s}  status"]
    for package in sorted(coverages):
        covered, total = coverages[package]
        percent = 100.0 * covered / total if total else 0.0
        if package in PACKAGE_THRESHOLDS:
            floor = f"{PACKAGE_THRESHOLDS[package]:.0f}%"
            status = "ok" if percent >= PACKAGE_THRESHOLDS[package] else "BELOW"
        elif package in REPORT_ONLY_PACKAGES:
            floor, status = "-", "reported"
        else:
            floor, status = "-", "not gated"
        lines.append(
            f"{package:12s} {covered:6d}/{total:<6d} {percent:6.1f}% {floor:>7s}  {status}"
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    report_path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    if not report_path.is_file():
        print(f"coverage report not found: {report_path}", file=sys.stderr)
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    files = report.get("files", {})
    if not isinstance(files, dict) or not files:
        print(f"coverage report has no files: {report_path}", file=sys.stderr)
        return 2

    coverages = package_coverages(files)
    print(render_table(coverages))
    violations = find_violations(coverages)
    if violations:
        print("\nCoverage gate failed:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    print("\nCoverage gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
