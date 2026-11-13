"""Badge dinamico de cobertura: redondeo, colores y codigos de salida (T-6.6).

El script corre en CI despues del gate por paquete y su unica salida es un archivo que el
README muestra; por eso sus dos reglas -el numero que se muestra y el color que lo
acompana- se prueban aqui sobre reportes sinteticos en `tmp_path`, sin reportes reales, sin
red y sin mocks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.coverage_badge_json import (
    BADGE_LABEL,
    GREEN_FLOOR,
    YELLOW_FLOOR,
    CoverageReportError,
    badge_color,
    badge_payload,
    main,
    read_total_percent,
    write_badge,
)

#: El script tal como lo invoca CI: como programa, no como funcion importada.
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "coverage_badge_json.py"


def _report(tmp_path: Path, percent: float | str | None) -> Path:
    """Reporte sintetico con la forma que produce `pytest-cov --cov-report=json`."""
    totals: dict[str, object] = {"num_statements": 120, "covered_lines": 101}
    if percent is not None:
        totals["percent_covered"] = percent
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"totals": totals, "files": {}}), encoding="utf-8")
    return path


def test_badge_payload_rounds_the_total_to_one_decimal() -> None:
    """El numero publicado se redondea a un decimal, no trunca ni arrastra precision."""
    assert badge_payload(84.234)["message"] == "84.2%"
    assert badge_payload(84.26)["message"] == "84.3%"
    assert badge_payload(100)["message"] == "100.0%"
    assert badge_payload(0)["message"] == "0.0%"


def test_badge_payload_uses_the_three_colour_buckets_at_their_boundaries() -> None:
    """Verde en el piso 80, amarillo en el piso 60 y rojo por debajo: sin huecos."""
    assert (GREEN_FLOOR, YELLOW_FLOOR) == (80.0, 60.0)
    assert badge_color(100.0) == "green"
    assert badge_color(80.0) == "green"
    assert badge_color(79.9) == "yellow"
    assert badge_color(60.0) == "yellow"
    assert badge_color(59.9) == "red"
    assert badge_color(0.0) == "red"


def test_badge_payload_colours_the_number_it_shows_not_the_raw_one() -> None:
    """El color se calcula sobre el numero ya redondeado, asi que nunca se contradicen."""
    near_green = badge_payload(79.96)
    assert near_green["message"] == "80.0%"
    assert near_green["color"] == "green"

    near_red = badge_payload(59.96)
    assert near_red["message"] == "60.0%"
    assert near_red["color"] == "yellow"


def test_badge_payload_is_a_shields_io_endpoint_document() -> None:
    """La forma exacta que shields.io espera en `endpoint?url=...`."""
    payload = badge_payload(84.234)
    assert payload == {
        "schemaVersion": 1,
        "label": BADGE_LABEL,
        "message": "84.2%",
        "color": "green",
    }
    assert BADGE_LABEL == "coverage"


def test_read_total_percent_returns_the_reported_total(tmp_path: Path) -> None:
    """Se lee `totals.percent_covered`, que es el agregado del reporte, no un archivo."""
    assert read_total_percent(_report(tmp_path, 84.235)) == 84.235


def test_read_total_percent_rejects_a_missing_report(tmp_path: Path) -> None:
    """Sin reporte no hay badge: el mensaje nombra la ruta que se busco."""
    missing = tmp_path / "nope.json"
    with pytest.raises(CoverageReportError, match="coverage report not found") as excinfo:
        read_total_percent(missing)
    assert str(missing) in str(excinfo.value)


def test_read_total_percent_rejects_a_report_without_a_percentage(tmp_path: Path) -> None:
    """`totals` ausente, vacio o con un valor que no es numero: los tres son error."""
    no_totals = tmp_path / "no-totals.json"
    no_totals.write_text(json.dumps({"files": {}}), encoding="utf-8")
    with pytest.raises(CoverageReportError, match=r"totals\.percent_covered"):
        read_total_percent(no_totals)

    with pytest.raises(CoverageReportError, match=r"totals\.percent_covered"):
        read_total_percent(_report(tmp_path, None))

    with pytest.raises(CoverageReportError, match=r"totals\.percent_covered"):
        read_total_percent(_report(tmp_path, "84.2"))


def test_read_total_percent_rejects_a_file_that_is_not_json(tmp_path: Path) -> None:
    """Un archivo corrupto se reporta como error de lectura, no como cobertura cero."""
    corrupt = tmp_path / "coverage.json"
    corrupt.write_text("{not json", encoding="utf-8")
    with pytest.raises(CoverageReportError, match="cannot read coverage report"):
        read_total_percent(corrupt)


def test_write_badge_creates_the_output_directory_and_returns_the_payload(
    tmp_path: Path,
) -> None:
    """La escritura crea el directorio del artifact y el archivo coincide con el payload."""
    report = _report(tmp_path, 84.234)
    output = tmp_path / "badge-out" / "coverage.json"

    payload = write_badge(report, output)

    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert payload["message"] == "84.2%"


def test_main_writes_the_endpoint_json_and_prints_it(tmp_path: Path, capsys) -> None:
    """Camino feliz del CLI: sale 0, imprime el JSON y lo escribe en `--output`."""
    report = _report(tmp_path, 84.234)
    output = tmp_path / "badge-out" / "coverage.json"

    assert main([str(report), "--output", str(output)]) == 0

    written = json.loads(output.read_text(encoding="utf-8"))
    printed = json.loads(capsys.readouterr().out)
    assert printed == written
    assert written["message"] == "84.2%"
    assert written["color"] == "green"


def test_main_uses_coverage_json_when_no_report_is_given(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """El reporte es opcional en la linea de comandos: por defecto `coverage.json`."""
    (tmp_path / "coverage.json").write_text(
        json.dumps({"totals": {"percent_covered": 90.04}}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert main(["--output", "badge-out/coverage.json"]) == 0

    assert json.loads(capsys.readouterr().out)["message"] == "90.0%"
    assert (tmp_path / "badge-out" / "coverage.json").is_file()


def test_main_fails_with_exit_code_2_when_the_report_is_missing(tmp_path: Path, capsys) -> None:
    """Sin reporte: codigo 2, mensaje en stderr y ningun badge escrito."""
    output = tmp_path / "badge-out" / "coverage.json"

    assert main([str(tmp_path / "nope.json"), "--output", str(output)]) == 2

    captured = capsys.readouterr()
    assert "coverage report not found" in captured.err
    assert captured.out == ""
    assert not output.exists()


def test_main_fails_with_exit_code_2_when_the_report_has_no_total(tmp_path: Path, capsys) -> None:
    """Un reporte sin `totals.percent_covered` no publica un badge inventado."""
    report = _report(tmp_path, None)
    output = tmp_path / "badge-out" / "coverage.json"

    assert main([str(report), "--output", str(output)]) == 2

    captured = capsys.readouterr()
    assert "totals.percent_covered" in captured.err
    assert not output.exists()


def test_main_requires_the_output_argument(tmp_path: Path, capsys) -> None:
    """`--output` es obligatorio: sin el no hay donde publicar y argparse corta con 2."""
    report = _report(tmp_path, 84.234)

    with pytest.raises(SystemExit) as excinfo:
        main([str(report)])

    assert excinfo.value.code == 2
    assert "--output" in capsys.readouterr().err


def test_the_script_works_when_run_as_a_program(tmp_path: Path) -> None:
    """CI lo ejecuta como programa: la linea de comandos real tambien publica el badge."""
    report = _report(tmp_path, 84.234)
    output = tmp_path / "badge-out" / "coverage.json"

    result = subprocess.run(  # noqa: S603 - argv literal, sin shell: el propio script del repo
        [sys.executable, str(SCRIPT_PATH), "--output", str(output), str(report)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == json.loads(result.stdout)
    assert written["message"] == "84.2%"


def test_the_script_run_as_a_program_fails_on_a_missing_report(tmp_path: Path) -> None:
    """El programa sale con 2 y un mensaje claro cuando el reporte no existe."""
    output = tmp_path / "badge-out" / "coverage.json"

    result = subprocess.run(  # noqa: S603 - argv literal, sin shell: el propio script del repo
        [sys.executable, str(SCRIPT_PATH), "--output", str(output), str(tmp_path / "nope.json")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "coverage report not found" in result.stderr
    assert result.stdout == ""
    assert not output.exists()
