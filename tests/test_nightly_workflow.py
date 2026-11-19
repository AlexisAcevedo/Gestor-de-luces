"""Regression pins for `.github/workflows/nightly.yml` (nightly flake check).

The nightly exists to catch flaky tests, so it must fail for the same reasons `ci.yml` fails.
Running the repeats inside one process (`--count=5` from pytest-repeat) mixes a real defect with
the state the previous passes left behind in the same interpreter, which is invisible to whoever
reads the notification. These tests pin the shape of the step: five separate `pytest` processes,
fail-fast, and no in-process repetition.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash is required to execute a workflow step")

INDENT = 10  # `run: |` sits at 8 spaces, so the body of every shell step starts at 10

SUITE_STEP = "name: Run the whole suite five times"
FAILING_PASS = 3


def _step_body(marker: str) -> str:
    """Return the shell body of the step that contains `marker`."""
    lines = WORKFLOW.splitlines()
    marker_index = next(i for i, line in enumerate(lines) if marker in line)
    run_index = next(
        (i for i in range(marker_index, len(lines)) if lines[i].strip() == "run: |"),
        None,
    )
    assert run_index is not None, (
        f"el paso '{marker}' ya no declara un bloque `run: |`: "
        "un `run:` inline no se puede ejecutar"
    )
    body: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and not line.startswith(" " * INDENT):
            break
        body.append(line[INDENT:] if line.strip() else "")
    return "\n".join(body) + "\n"


def test_nightly_executes_a_fresh_pytest_process_per_pass() -> None:
    """Cinco procesos separados: ninguna repeticion dentro del mismo interprete."""
    body = _step_body(SUITE_STEP)

    assert "--count" not in body, "las repeticiones vuelven a compartir el proceso del nightly"
    assert "pytest -x --timeout=120" in body, "se perdio el fail-fast o el limite de dos minutos"
    assert "for pass in 1 2 3 4 5" in body, "el nightly ya no corre exactamente cinco pasadas"


def _run_suite_step(
    tmp_path: Path, *, failing_pass: int | None
) -> tuple[subprocess.CompletedProcess[str], int]:
    """Execute the suite step with a `pytest` stub that counts its invocations."""
    counter = tmp_path / "counter"
    counter.write_text("0", encoding="utf-8")

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "pytest"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'count=$(( $(cat "$COUNTER") + 1 ))\n'
        'echo "$count" > "$COUNTER"\n'
        f'if [ "$count" -eq {failing_pass or 0} ]; then exit 3; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    script = tmp_path / "step.sh"
    script.write_text(_step_body(SUITE_STEP), encoding="utf-8")

    env = dict(os.environ)
    env["COUNTER"] = str(counter)
    env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
    completed = subprocess.run(  # noqa: S603 - fixed bash binary, stub script we just wrote
        [BASH, str(script)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    return completed, int(counter.read_text(encoding="utf-8").strip())


@needs_bash
def test_nightly_runs_five_passes_when_the_suite_is_green(tmp_path: Path) -> None:
    """Una suite verde se corre cinco veces y el paso termina en cero."""
    completed, runs = _run_suite_step(tmp_path, failing_pass=None)

    assert completed.returncode == 0, completed.stderr
    assert runs == 5
    assert "Pass 5 of 5" in completed.stdout


@needs_bash
def test_nightly_stops_at_the_failing_pass_and_propagates_its_exit_code(tmp_path: Path) -> None:
    """La pasada fallida corta la serie con su propio codigo de salida."""
    completed, runs = _run_suite_step(tmp_path, failing_pass=FAILING_PASS)

    assert runs == FAILING_PASS, "el nightly siguio corriendo despues de una pasada fallida"
    assert completed.returncode == 3, completed.stderr
    assert f"Pass {FAILING_PASS} of 5" in completed.stdout
    assert f"Pass {FAILING_PASS + 1} of 5" not in completed.stdout
