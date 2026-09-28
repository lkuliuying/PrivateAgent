"""执行发布工作流的真实 PowerShell 门禁，用合成 Git/GitHub 回执验证发布边界。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/signpath-release.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
STEPS = {
    match.group(1): match.group(2)
    for match in re.finditer(r"^      - name: ([^\n]+)\n(.*?)(?=^      - name: |\Z)", TEXT, re.M | re.S)
}
PREFLIGHT = "Validate tagged source and existing draft"
UPLOAD = "Attach verified assets to the existing draft"
ASSET_NAMES = [
    "PrivateAgent_1.0.0_x64-setup.exe",
    "PrivateAgent_1.0.0_x64-setup.exe.sig",
    "latest.json",
    "release-verification-1.0.0.json",
    "release-manifest-1.0.0.md",
]
MOCK_COMMANDS = r"""
function git {
  $global:LASTEXITCODE = [int]$env:MOCK_GIT_EXIT
  if ($args[0] -eq 'rev-parse' -and $args[1] -eq 'HEAD') { return $env:MOCK_HEAD_COMMIT }
  if ($args[0] -eq 'rev-parse' -and $args[1] -eq "refs/tags/$($env:RELEASE_TAG)^{commit}") { return $env:MOCK_TAG_COMMIT }
  if ($args[0] -eq 'status' -and $args[1] -eq '--porcelain') { return $env:MOCK_GIT_STATUS }
  throw 'Unexpected Git command in the offline test'
}
function gh {
  ConvertTo-Json -InputObject @($args) -Compress | Add-Content -LiteralPath $env:MOCK_GH_CALLS -Encoding utf8
  if ($args[0] -cne 'release') { throw 'Unexpected GitHub command in the offline test' }
  if ($args[1] -ceq 'view') {
    $global:LASTEXITCODE = [int]$env:MOCK_VIEW_EXIT
    return Get-Content -LiteralPath $env:MOCK_RELEASE_JSON -Raw
  }
  if ($args[1] -ceq 'upload') { $global:LASTEXITCODE = [int]$env:MOCK_UPLOAD_EXIT; return }
  throw 'Only release view/upload can be simulated'
}
function python { & $env:TEST_PYTHON @args }
"""


def run_body(name: str) -> str:
    block = STEPS[name]
    match = re.search(r"^        run: \|\n((?:          .*\n|\n)*)", block, re.M)
    assert match, name
    return "\n".join(line[10:] for line in match.group(1).splitlines()) + "\n"


@pytest.fixture
def release_context(tmp_path):
    tauri = tmp_path / "apps/desktop/src-tauri"
    tauri.mkdir(parents=True)
    (tauri / "tauri.conf.json").write_text(json.dumps({
        "version": "1.0.0", "identifier": "com.personal-assistant.desktop",
    }), encoding="utf-8")
    (tauri.parent / "package.json").write_text('{"version":"1.0.0"}', encoding="utf-8")
    (tauri / "Cargo.toml").write_text('[package]\nversion = "1.0.0"\n', encoding="utf-8")
    release = {"id": "RE_test_release", "tagName": "v1.0.0", "isDraft": True, "isPrerelease": False, "assets": []}
    # 显式白名单避免子进程继承本机凭据；所有 GitHub 调用均由进程内函数替身处理。
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "SYSTEMDRIVE", "TEMP", "TMP"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update({
        "GITHUB_REPOSITORY": "lkuliuying/PrivateAgent",
        "RELEASE_REPOSITORY": "lkuliuying/PrivateAgent",
        "RELEASE_TAG": "v1.0.0",
        "RELEASE_VERSION": "1.0.0",
        "GITHUB_OUTPUT": str(tmp_path / "github-output.txt"),
        "EXPECTED_RELEASE_ID": "RE_test_release",
        "MOCK_HEAD_COMMIT": "a" * 40,
        "MOCK_TAG_COMMIT": "a" * 40,
        "MOCK_GIT_EXIT": "0",
        "MOCK_GIT_STATUS": "",
        "MOCK_VIEW_EXIT": "0",
        "MOCK_UPLOAD_EXIT": "0",
        "MOCK_RELEASE_JSON": str(tmp_path / "release.json"),
        "MOCK_GH_CALLS": str(tmp_path / "gh-calls.jsonl"),
        "TEST_PYTHON": sys.executable,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    })
    for key, name in zip(("INSTALLER_PATH", None, "MANIFEST_PATH", "VERIFICATION_PATH", "RELEASE_MANIFEST_PATH"), ASSET_NAMES, strict=True):
        asset = tmp_path / name
        asset.write_bytes(b"offline-test-asset")
        if key:
            env[key] = str(asset)
    return tmp_path, release, env


def execute(name, context):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("需要 PowerShell 执行工作流门禁")
    directory, release, env = context
    Path(env["MOCK_RELEASE_JSON"]).write_text(json.dumps(release), encoding="utf-8")
    script = directory / "workflow-step.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n" + MOCK_COMMANDS + run_body(name), encoding="utf-8-sig")
    return subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=directory, env=env, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
    )


def gh_calls(context):
    path = Path(context[2]["MOCK_GH_CALLS"])
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()] if path.exists() else []


def test_workflow_is_manual_tagged_and_secret_scoped():
    triggers = TEXT.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.findall(r"^  ([a-z_]+):", triggers, re.M) == ["workflow_dispatch"]
    checkout = STEPS["Check out the release tag"]
    assert "ref: refs/tags/${{ inputs.release_tag }}" in checkout
    assert "persist-credentials: false" in checkout
    assert "SIGNPATH_" not in TEXT
    assert "--clobber" not in TEXT
    assert not re.search(r"gh release (create|edit|delete)", TEXT)
    for name, block in STEPS.items():
        if "TAURI_SIGNING_PRIVATE_KEY" in block:
            assert name == "Build the Tauri-signed Windows installer"
        if "        run: |" in block:
            assert "${{" not in run_body(name)
    assert "TAURI_SIGNING_PRIVATE_KEY" not in TEXT.split("    steps:", 1)[0]
    cache_path = re.search(r"^      UV_CACHE_DIR: (.+)$", TEXT, re.M).group(1)
    assert cache_path == "${{ runner.temp }}\\privateagent-uv-cache"
    assert "--github-repo $env:RELEASE_REPOSITORY" in run_body("Build the Tauri-signed Windows installer")
    assert "scripts/verify_update_release.py" in run_body("Verify final updater assets and record evidence")
    assert all(re.fullmatch(r"[0-9a-f]{40}", pin) for pin in re.findall(r"uses: [^@]+@([^\s]+)", TEXT))


def test_all_powershell_blocks_parse(release_context):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("需要 PowerShell 检查工作流语法")
    directory, _, env = release_context
    parsed = 0
    for index, (name, block) in enumerate(STEPS.items()):
        if "        run: " not in block:
            continue
        path = directory / f"block-{index}.ps1"
        body = run_body(name) if "        run: |" in block else re.search(r"^        run: ([^\n]+)", block, re.M).group(1)
        path.write_text(body, encoding="utf-8-sig")
        parsed += 1
    assert parsed == 7
    parser = directory / "parse.ps1"
    parser.write_text("""$ErrorActionPreference = 'Stop'
Get-ChildItem -LiteralPath $env:TEST_SCRIPT_DIRECTORY -Filter 'block-*.ps1' | ForEach-Object {
  $tokens = $null
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors)
  if ($errors.Count -gt 0) { throw ($errors | Out-String) }
}
""", encoding="utf-8-sig")
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(parser)],
                            env={**env, "TEST_SCRIPT_DIRECTORY": str(directory)}, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("tag", ["1.0.0", "remote-v1.0.0", "v1.0.0-rc.1", "v01.0.0", "v1.0", "v1.0.0\n", "v1.0.0; throw 'injected'"])
def test_input_rejects_nonrelease_tags(tag, release_context):
    release_context[2]["RELEASE_TAG"] = tag
    result = execute("Validate release input", release_context)
    assert result.returncode != 0
    assert "Release tag must be" in result.stderr
    assert not gh_calls(release_context)


def test_input_accepts_formal_tag_and_rejects_other_repository(release_context):
    assert execute("Validate release input", release_context).returncode == 0
    release_context[2]["GITHUB_REPOSITORY"] = "another/repository"
    result = execute("Validate release input", release_context)
    assert result.returncode != 0
    assert "Unexpected release repository" in result.stderr


def test_preflight_records_verified_source_and_draft(release_context):
    result = execute(PREFLIGHT, release_context)
    assert result.returncode == 0, result.stderr
    output = Path(release_context[2]["GITHUB_OUTPUT"]).read_text(encoding="utf-8-sig")
    assert "version=1.0.0" in output
    assert f"commit={'a' * 40}" in output
    assert "release_id=RE_test_release" in output
    assert [call[:2] for call in gh_calls(release_context)] == [["release", "view"]]


@pytest.mark.parametrize("file", ["apps/desktop/src-tauri/tauri.conf.json", "apps/desktop/package.json", "apps/desktop/src-tauri/Cargo.toml"])
def test_preflight_rejects_each_source_version_mismatch(file, release_context):
    path = release_context[0] / file
    path.write_text(path.read_text(encoding="utf-8").replace("1.0.0", "1.0.1"), encoding="utf-8")
    result = execute(PREFLIGHT, release_context)
    assert result.returncode != 0
    assert "Release tag does not match" in result.stderr
    assert not gh_calls(release_context)


@pytest.mark.parametrize("key,value,message", [
    ("MOCK_TAG_COMMIT", "b" * 40, "Checked-out commit does not match"),
    ("MOCK_GIT_EXIT", "1", "Cannot resolve checked-out commit"),
    ("MOCK_GIT_STATUS", " M tracked-file", "clean Git working tree"),
    ("MOCK_VIEW_EXIT", "1", "release draft must already exist"),
])
def test_preflight_rejects_invalid_source_or_missing_draft(key, value, message, release_context):
    release_context[2][key] = value
    result = execute(PREFLIGHT, release_context)
    assert result.returncode != 0
    assert message in result.stderr
    assert not any(call[:2] == ["release", "upload"] for call in gh_calls(release_context))


@pytest.mark.parametrize("stage", [PREFLIGHT, UPLOAD])
@pytest.mark.parametrize("update", [
    {"isDraft": False}, {"isPrerelease": True}, {"tagName": "v1.0.1"}, {"id": ""},
    {"assets": [{"name": "latest.json"}]},
])
def test_each_gate_rejects_wrong_release_state(stage, update, release_context):
    release_context[1].update(update)
    result = execute(stage, release_context)
    assert result.returncode != 0
    assert not any(call[:2] == ["release", "upload"] for call in gh_calls(release_context))


def test_preflight_rejects_other_application_identifier(release_context):
    path = release_context[0] / "apps/desktop/src-tauri/tauri.conf.json"
    path.write_text('{"version":"1.0.0","identifier":"com.personal-assistant.desktop.candidate"}', encoding="utf-8")
    result = execute(PREFLIGHT, release_context)
    assert result.returncode != 0
    assert "Unexpected application identifier" in result.stderr


def test_upload_attaches_only_five_assets_without_publishing(release_context):
    result = execute(UPLOAD, release_context)
    assert result.returncode == 0, result.stderr
    calls = gh_calls(release_context)
    assert [call[:2] for call in calls] == [["release", "view"], ["release", "upload"]]
    upload = calls[1]
    assert upload[2] == "v1.0.0"
    assert [Path(path).name for path in upload[3:8]] == ASSET_NAMES
    assert upload[8:] == ["--repo", "lkuliuying/PrivateAgent"]


@pytest.mark.parametrize("change,message", [
    ("recreated", "Release draft changed"), ("missing", "Cannot find path"),
    ("empty", "Unexpected or empty upload asset"), ("other-name", "Unexpected or empty upload asset"),
    ("view-fails", "Cannot recheck the release draft"),
])
def test_upload_stops_when_draft_or_local_assets_change(change, message, release_context):
    directory, release, env = release_context
    if change == "recreated":
        release["id"] = "RE_recreated_release"
    elif change == "missing":
        Path(env["INSTALLER_PATH"]).unlink()
    elif change == "empty":
        Path(env["MANIFEST_PATH"]).write_bytes(b"")
    elif change == "other-name":
        other = directory / "PrivateAgentRemote_1.0.0_x64-setup.exe"
        other.write_bytes(b"wrong-target")
        env["INSTALLER_PATH"] = str(other)
    else:
        env["MOCK_VIEW_EXIT"] = "1"
    result = execute(UPLOAD, release_context)
    assert result.returncode != 0
    assert message in result.stderr
    assert not any(call[:2] == ["release", "upload"] for call in gh_calls(release_context))


def test_upload_failure_is_not_reported_as_success(release_context):
    release_context[2]["MOCK_UPLOAD_EXIT"] = "1"
    result = execute(UPLOAD, release_context)
    assert result.returncode != 0
    assert "Draft asset upload failed" in result.stderr
    assert "Verified assets attached" not in result.stdout
