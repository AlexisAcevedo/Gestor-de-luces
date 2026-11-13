"""Gate de cobertura por paquete: agregacion, umbrales y veredicto (T-6.6).

El script de CI no se prueba ejecutando pytest ni leyendo un reporte real: se prueba su
logica pura (`package_coverages`, `find_violations`, `render_table`) con reportes sinteticos,
que es donde vive la regla que puede romperse en silencio.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_coverage import (
    PACKAGE_THRESHOLDS,
    TOP_LEVEL_KEY,
    find_violations,
    main,
    package_coverages,
    package_key,
    render_table,
)


def _entry(covered: int, statements: int) -> dict[str, object]:
    return {"summary": {"covered_lines": covered, "num_statements": statements}}


def test_package_key_groups_by_package_and_falls_back_to_top_level() -> None:
    """Un archivo dentro de un paquete cuenta para ese paquete; uno suelto va a `(top-level)`."""
    assert package_key("D:\\wt\\src\\gestor_luces\\domain\\models.py") == "domain"
    assert package_key("/wt/src/gestor_luces/adapters/tray/winforms_menu.py") == "adapters"
    assert package_key("src/gestor_luces/main.py") == TOP_LEVEL_KEY
    assert package_key("src/otro_paquete/x.py") == TOP_LEVEL_KEY


def test_package_coverages_sums_the_files_of_each_package() -> None:
    """Las lineas se suman por paquete, no se promedian por archivo."""
    files = {
        "src/gestor_luces/domain/models.py": _entry(50, 50),
        "src/gestor_luces/domain/scenes.py": _entry(40, 50),
        "src/gestor_luces/adapters/a.py": _entry(10, 20),
        "src/gestor_luces/main.py": _entry(1, 4),
    }
    assert package_coverages(files) == {
        "domain": (90, 100),
        "adapters": (10, 20),
        TOP_LEVEL_KEY: (1, 4),
    }


def test_find_violations_reports_each_package_below_its_floor_and_ignores_reported_ones() -> None:
    """Un paquete bajo su piso es violacion; `ports`/`desktop` y `(top-level)` no se gatean."""
    coverages = {
        "domain": (89, 100),
        "application": (80, 100),
        "adapters": (10, 100),
        "ports": (0, 10),
        "desktop": (0, 10),
        TOP_LEVEL_KEY: (0, 10),
    }
    violations = find_violations(coverages)
    assert len(violations) == 2
    assert any(v.startswith("domain: 89.0%") and "90" in v for v in violations)
    assert any(v.startswith("adapters: 10.0%") and "55" in v for v in violations)
    assert not any("ports" in v or "desktop" in v for v in violations)


def test_find_violations_reports_a_missing_gated_package() -> None:
    """Un reporte sin un paquete obligatorio no pasa por omision: es una violacion explicita."""
    violations = find_violations({"domain": (95, 100), "adapters": (90, 100)})
    assert violations == ["application: missing from the coverage report (needs >= 75%)"]


def test_render_table_shows_every_package_with_its_verdict() -> None:
    """La tabla informa cobertura, piso y veredicto de cada paquete del reporte."""
    table = render_table({"domain": (100, 100), "ports": (10, 10), "main": (1, 2)})
    assert "domain" in table and "100.0%" in table and "ok" in table
    assert "ports" in table and "reported" in table
    assert "main" in table and "not gated" in table
    assert set(PACKAGE_THRESHOLDS) == {"domain", "application", "adapters"}


def test_main_fails_on_a_missing_report_and_on_a_package_below_its_floor(
    tmp_path: Path, capsys
) -> None:
    """El script devuelve 2 si no hay reporte, 1 si un paquete baja y 0 cuando todo pasa."""
    missing = tmp_path / "nope.json"
    assert main(["check_coverage.py", str(missing)]) == 2

    failing = tmp_path / "failing.json"
    failing.write_text(
        json.dumps(
            {
                "files": {
                    "src/gestor_luces/domain/models.py": _entry(80, 100),
                    "src/gestor_luces/application/x.py": _entry(80, 100),
                    "src/gestor_luces/adapters/y.py": _entry(60, 100),
                }
            }
        ),
        encoding="utf-8",
    )
    assert main(["check_coverage.py", str(failing)]) == 1
    captured = capsys.readouterr()
    assert "Coverage gate failed" in captured.err
    assert "domain" in captured.err

    passing = tmp_path / "passing.json"
    passing.write_text(
        json.dumps(
            {
                "files": {
                    "src/gestor_luces/domain/models.py": _entry(95, 100),
                    "src/gestor_luces/application/x.py": _entry(80, 100),
                    "src/gestor_luces/adapters/y.py": _entry(60, 100),
                }
            }
        ),
        encoding="utf-8",
    )
    assert main(["check_coverage.py", str(passing)]) == 0
    assert "Coverage gate passed" in capsys.readouterr().out
