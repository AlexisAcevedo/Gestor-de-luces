"""Regression checks for packaging scripts, installer, spec, and CI workflows (Stage 6)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_ps1_signs_exe_before_zip_and_installer_with_https_timestamp() -> None:
    build_ps1 = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8")

    assert "https://timestamp.digicert.com" in build_ps1
    assert "http://timestamp" not in build_ps1

    sign_exe_idx = build_ps1.index("dist\\WizConsole\\WizConsole.exe")
    zip_idx = build_ps1.index("Compress-Archive")
    iscc_idx = build_ps1.index("packaging\\installer.iss")
    assert sign_exe_idx < zip_idx < iscc_idx


def test_installer_iss_hardening_and_localization() -> None:
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")

    assert "AppId={{6B1E2C0A-3F1B-4D7E-9A55-5C0B7D1E8F42}" in iss
    assert "runasoriginaluser" in iss
    assert 'ValueType: none; ValueName: "WizConsole"; Flags: uninsdeletevalue' in iss
    assert 'ValueType: none; ValueName: "GestorDeLuces"; Flags: deletevalue uninsdeletevalue' in iss
    assert "[CustomMessages]" in iss
    assert "english.AutostartTask=" in iss
    assert "spanish.AutostartTask=" in iss
    assert "english.WebView2Missing=" in iss
    assert "spanish.WebView2Missing=" in iss
    assert "CustomMessage('WebView2Missing')" in iss


def test_pyinstaller_spec_excludes_python_helper_scripts_from_assets() -> None:
    spec = (ROOT / "packaging" / "wiz_console.spec").read_text(encoding="utf-8")

    assert 'path.suffix != ".py"' in spec
    assert '(str(ROOT / "assets"), "assets")' not in spec


def test_all_github_workflows_pin_actions_by_full_commit_sha() -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    workflows = sorted(workflow_dir.glob("*.yml"))
    assert workflows

    uses_pattern = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
    sha_pattern = re.compile(r"^[^@]+@[0-9a-f]{40}$")
    for wf in workflows:
        text = wf.read_text(encoding="utf-8")
        refs = uses_pattern.findall(text)
        assert refs, f"{wf.name} contains no uses: entries"
        for ref in refs:
            assert sha_pattern.match(ref), f"{wf.name} has unpinned action ref: {ref}"


def test_ci_release_and_coverage_badge_workflow_policies() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "continue-on-error:" not in ci
    assert "permissions:\n  contents: read" in ci

    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "choco install innosetup --version=" in release

    badge = (ROOT / ".github" / "workflows" / "coverage-badge.yml").read_text(encoding="utf-8")
    assert "\npermissions:\n  contents: read\n" in badge
    assert "    permissions:\n      contents: write\n" in badge
    expected_concurrency = (
        "    concurrency:\n      group: coverage-badge\n      cancel-in-progress: false\n"
    )
    assert expected_concurrency in badge
