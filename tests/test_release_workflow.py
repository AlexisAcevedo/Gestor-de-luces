"""Regression pins for `.github/workflows/release.yml` (S1-S8 of odd/tasks/release-cd.md).

The workflow decides what reaches users, so the invariants that keep a broken build from becoming
a release are pinned here instead of being re-read by hand. The steps that are pure shell are
executed against stub inputs: a `gh` stub for the publish step, synthetic `dist/` trees for the
artifact set, and synthetic event variables for the guard.

Verified 2026-11-17 against the 0.4.1 `dist/`: `sha256sum -c SHA256SUMS.txt` reports both
artifacts OK and the frozen `GestorDeLuces.exe --smoke-test` exits 0.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
DECLARED_VERSION = (
    (ROOT / "pyproject.toml").read_text(encoding="utf-8").split('version = "')[1].split('"')[0]
)


def _find_bash() -> str | None:
    """Resolve Git Bash on Windows (skipping WSL/WindowsApps stubs) or `bash` on POSIX."""
    if os.name != "nt":
        return shutil.which("bash")
    candidates: list[Path] = []
    git_exe = shutil.which("git")
    if git_exe:
        git_root = Path(git_exe).resolve().parent.parent
        candidates.extend([git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"])
    candidates.extend(
        [
            Path(r"C:\Program Files\Git\bin\bash.exe"),
            Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
            Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    which_bash = shutil.which("bash")
    if which_bash and not any(bad in which_bash.lower() for bad in ("system32", "windowsapps")):
        return which_bash
    return None


BASH = _find_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="bash is required to execute a workflow step")

INDENT = 10  # `run: |` sits at 8 spaces, so the body of every shell step starts at 10


def _step_lines(marker: str) -> tuple[list[str], int, str | None]:
    """Return (workflow lines, run index, working-directory) of the step containing `marker`."""
    lines = WORKFLOW.splitlines()
    marker_index = next(i for i, line in enumerate(lines) if marker in line)
    run_index = next(i for i in range(marker_index, len(lines)) if lines[i].strip() == "run: |")
    working_directory = None
    for line in lines[marker_index:run_index]:
        if line.strip().startswith("working-directory:"):
            working_directory = line.split(":", 1)[1].strip()
    return lines, run_index, working_directory


def _step_body(marker: str) -> str:
    """Return the shell body of the step that contains `marker`."""
    lines, run_index, _ = _step_lines(marker)
    body: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and not line.startswith(" " * INDENT):
            break
        body.append(line[INDENT:] if line.strip() else "")
    return "\n".join(body) + "\n"


def _run_step(tmp_path: Path, marker: str, extra_env: dict[str, str], gh_stub: str | None = None):
    """Execute one extracted step; returns (completed process, gh argument log)."""
    script = tmp_path / "step.sh"
    script.write_text(_step_body(marker), encoding="utf-8", newline="\n")
    _, _, working_directory = _step_lines(marker)
    cwd = tmp_path / working_directory if working_directory else tmp_path
    env = dict(os.environ, GITHUB_RUN_NUMBER="7", GITHUB_SHA="c0ffee")
    env["GITHUB_STEP_SUMMARY"] = str(tmp_path / "summary.txt")
    env["RUNNER_TEMP"] = str(tmp_path)
    env.update(extra_env)
    if gh_stub is not None:
        binary_dir = tmp_path / "bin"
        binary_dir.mkdir()
        stub = binary_dir / "gh"
        stub.write_text(gh_stub, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
        log = tmp_path / "gh.log"
        log.write_text("", encoding="utf-8")
        env["GH_LOG"] = str(log)
        env["PATH"] = str(binary_dir) + os.pathsep + env.get("PATH", "")
    # The script is the workflow step under test, not untrusted input.
    completed = subprocess.run(  # noqa: S603
        [BASH, str(script)], cwd=cwd, env=env, capture_output=True, text=True, timeout=60
    )
    log = (tmp_path / "gh.log").read_text(encoding="utf-8") if gh_stub is not None else ""
    return completed, log


GH_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GH_LOG"
if [ "$1 $2" = "release view" ]; then
  if [ "$GH_VIEW" = "missing" ]; then
    echo "release not found" >&2
    exit 1
  fi
  echo "$GH_VIEW"
fi
exit 0
"""


def test_s1_a_tag_builds_on_a_windows_runner_without_a_manual_version() -> None:
    assert "tags: ['v*']" in WORKFLOW
    assert "workflow_dispatch:" in WORKFLOW
    assert "runs-on: windows-latest" in WORKFLOW
    assert "./scripts/build.ps1 -Python python" in WORKFLOW
    # build.ps1 reads pyproject.toml; a version argument would be invented and ignored.
    assert "-Version " not in WORKFLOW


def test_s2_verification_precedes_publication() -> None:
    assert "needs: [guard, verify]" in WORKFLOW
    assert "sha256sum -c SHA256SUMS.txt" in WORKFLOW
    assert "./WizConsole/WizConsole.exe --smoke-test" in WORKFLOW
    verified_at = WORKFLOW.index("sha256sum -c SHA256SUMS.txt")
    assert verified_at < WORKFLOW.index('gh release create "$TAG"')


@needs_bash
def test_s3_the_artifact_set_is_exactly_three_files(tmp_path: Path) -> None:
    version = "9.9.9"
    names = [f"WizConsole-Setup-{version}.exe", f"WizConsole-portable-{version}.zip"]
    names.append("SHA256SUMS.txt")

    def build(layout: str) -> subprocess.CompletedProcess:
        dist = tmp_path / "dist"
        shutil.rmtree(dist, ignore_errors=True)
        dist.mkdir()
        (dist / "WizConsole").mkdir()
        (dist / "WizConsole" / "WizConsole.exe").write_bytes(b"MZ")
        for name in names:
            (dist / name).write_bytes(b"artifact")
        if layout == "extra":
            (dist / "unexpected.txt").write_bytes(b"?")
        if layout == "missing":
            (dist / names[1]).unlink()
        if layout == "nested-extra":
            (dist / "WizConsole" / "extra.dll").write_bytes(b"?")
        return _run_step(tmp_path, "name: Check the artifact set", {"VERSION": version})[0]

    assert build("honest").returncode == 0, build("honest").stdout
    # a stray file at the top of dist/ is what would get published unnoticed
    assert build("extra").returncode == 1
    assert build("missing").returncode == 1
    # the one-folder app directory is expected and must not break the file count
    assert build("nested-extra").returncode == 0


def test_s4_publish_is_serialised_on_the_release_identity() -> None:
    """A tag run and a dispatch must share one lock for the same release tag.

    Keying on the raw ref would give `v0.4.1` and `0.4.1` different groups for the same release,
    and the two publish steps could then interleave their uploads.
    """
    assert "\nconcurrency:" not in WORKFLOW
    publish = WORKFLOW.split("\n  publish:", 1)[1]
    assert "\n    concurrency:" in publish
    assert "group: release-${{ needs.guard.outputs.tag }}" in publish


@needs_bash
@pytest.mark.parametrize(
    ("view", "code", "creates"),
    [
        # a re-run of the same tag finds its own draft and reuses it
        ("true", 0, False),
        # no release yet: the draft is created
        ("missing", 0, True),
        # never overwrite a public release: --clobber would replace published assets
        ("false", 1, False),
    ],
)
def test_s4_a_published_release_is_never_clobbered(
    tmp_path: Path, view: str, code: int, creates: bool
) -> None:
    completed, log = _run_step(
        tmp_path,
        "name: Create the draft release",
        {"GH_VIEW": view, "TAG": "v9.9.9", "VERSION": "9.9.9"},
        gh_stub=GH_STUB,
    )
    assert completed.returncode == code, completed.stdout + completed.stderr
    assert ("release create" in log) is creates
    if code:
        assert "already published" in completed.stdout + completed.stderr


@needs_bash
@pytest.mark.parametrize(
    ("event", "ref", "version", "dry_run", "code", "expected"),
    [
        ("push", f"v{DECLARED_VERSION}", "", "", 0, f"tag=v{DECLARED_VERSION} dry_run=false"),
        (
            "workflow_dispatch",
            "feat/x",
            DECLARED_VERSION,
            "true",
            0,
            f"tag=v{DECLARED_VERSION}-dryrun-7",
        ),
        (
            "workflow_dispatch",
            "main",
            f"v{DECLARED_VERSION}",
            "false",
            0,
            f"tag=v{DECLARED_VERSION} dry_run=false",
        ),
        # a mismatched rehearsal tag: rejected because pyproject.toml declares another version
        ("push", "v0.0.0-draft", "", "", 1, "does not match pyproject.toml"),
        # a manual run must never fall back to the branch name
        ("workflow_dispatch", "feat/x", "", "true", 1, "is not a version"),
        ("push", f"v{DECLARED_VERSION}; id", "", "", 1, "is not a version"),
        ("push", "v9.9.9", "", "", 1, "does not match pyproject.toml"),
    ],
)
def test_s5_the_guard_refuses_an_inconsistent_version(
    tmp_path: Path, event: str, ref: str, version: str, dry_run: str, code: int, expected: str
) -> None:
    (tmp_path / "docs" / "releases").mkdir(parents=True)
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    declared = (ROOT / "pyproject.toml").read_text(encoding="utf-8").split('version = "')[1]
    (tmp_path / "docs" / "releases" / f"{declared.split(chr(34))[0]}.md").write_text("notes\n")

    completed, _ = _run_step(
        tmp_path,
        "id: resolve",
        {
            "EVENT_NAME": event,
            "REF_NAME": ref,
            "INPUT_VERSION": version,
            "INPUT_DRY_RUN": dry_run,
            "GITHUB_OUTPUT": str(tmp_path / "out.txt"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.txt"),
        },
    )
    assert completed.returncode == code, completed.stdout + completed.stderr
    if code == 0:
        produced = (tmp_path / "out.txt").read_text(encoding="utf-8").replace("\n", " ")
        assert expected in produced
    else:
        assert expected in completed.stdout + completed.stderr


@needs_bash
def test_s5_missing_release_notes_stop_a_matching_version(tmp_path: Path) -> None:
    declared = (ROOT / "pyproject.toml").read_text(encoding="utf-8").split('version = "')[1]
    version = declared.split('"')[0]
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")

    completed, _ = _run_step(
        tmp_path,
        "id: resolve",
        {
            "EVENT_NAME": "push",
            "REF_NAME": f"v{version}",
            "GITHUB_OUTPUT": str(tmp_path / "out.txt"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.txt"),
        },
    )
    assert completed.returncode == 1
    assert f"missing docs/releases/{version}.md" in completed.stdout + completed.stderr


def test_s6_notes_live_in_the_repository_and_are_required() -> None:
    assert '--notes-file "docs/releases/$VERSION.md"' in WORKFLOW
    assert "docs/releases/$version.md" in WORKFLOW
    assert "--generate-notes" not in WORKFLOW
    assert (ROOT / "docs" / "releases" / "0.4.1.md").is_file()
    assert (ROOT / "docs" / "releases" / f"{DECLARED_VERSION}.md").is_file()
    assert (ROOT / "docs" / "releases" / "README.md").is_file()


def test_s7_only_the_default_token_can_write() -> None:
    assert "\npermissions:\n  contents: read\n" in WORKFLOW
    publish = WORKFLOW.split("\n  publish:", 1)[1]
    assert "\n    permissions:\n      contents: write\n" in publish
    assert WORKFLOW.count("contents: write") == 1
    assert "${{ github.token }}" in WORKFLOW
    assert "secrets." not in WORKFLOW


def test_s8_the_other_workflows_keep_their_triggers() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "branches: [main]" in ci
    assert "pull_request:" in ci
    assert "js tests" in ci
    badge = (ROOT / ".github" / "workflows" / "coverage-badge.yml").read_text(encoding="utf-8")
    assert "branches: [main]" in badge
    nightly = (ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    assert "17 3 * * *" in nightly
