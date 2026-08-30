"""Exercise the deployment patch against an isolated Git working tree."""
import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("backend_bundle", ROOT / "scripts/prepare-connected-backend.py")
bundle_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle_tool)


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


@pytest.fixture
def prepared(tmp_path):
    archive = tmp_path / "backend.tar.gz"
    bundle_tool.create_bundle(ROOT, archive)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with tarfile.open(archive) as tar:
        assert set(tar.getnames()) == {"backend.patch", "manifest.json", "backend_tool.py"}
        tar.extractall(bundle, filter="data")
    server = tmp_path / "server"
    server.mkdir()
    git(server, "init", "--quiet")
    git(server, "config", "core.autocrlf", "false")
    for relative in bundle_tool.EXISTING:
        path = server / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(git(ROOT, "show", f"{bundle_tool.BASE_COMMIT}:{relative}").replace(b"\r\n", b"\n"))
    return server, bundle, archive


def test_apply_and_rollback_checks_preserve_unrelated_server_changes(prepared):
    server, bundle, _ = prepared
    unrelated = server / "alembic/env.py"
    unrelated.parent.mkdir()
    unrelated.write_text("# server-specific migration repair\n", encoding="utf-8")
    assert bundle_tool.verify_bundle(server, bundle, "before") == 5
    git(server, "apply", "--check", str(bundle / "backend.patch"))
    git(server, "apply", str(bundle / "backend.patch"))
    assert bundle_tool.verify_bundle(server, bundle, "after") == 5
    assert unrelated.read_text(encoding="utf-8") == "# server-specific migration repair\n"
    # No rollback is executed: checking proves the inverse patch is applicable.
    git(server, "apply", "--reverse", "--check", str(bundle / "backend.patch"))
    with pytest.raises(ValueError, match="does not match before"):
        bundle_tool.verify_bundle(server, bundle, "before")
    result = subprocess.run([
        sys.executable, "-B", str(bundle / "backend_tool.py"),
        "verify", "--root", str(server), "--state", "after",
    ], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"PASS: 5" in result.stdout


@pytest.mark.parametrize("relative", [bundle_tool.EXISTING[0], bundle_tool.ADDED[0]])
def test_conflicting_server_source_is_rejected_without_writes(prepared, relative):
    server, bundle, _ = prepared
    path = server / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# existing server change\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stop without overwriting"):
        bundle_tool.verify_bundle(server, bundle, "before")
    assert path.read_text(encoding="utf-8") == "# existing server change\n"


def test_corrupt_patch_is_rejected(prepared):
    server, bundle, _ = prepared
    with (bundle / "backend.patch").open("ab") as output:
        output.write(b"corruption\n")
    with pytest.raises(ValueError, match="Patch checksum mismatch"):
        bundle_tool.verify_bundle(server, bundle, "before")


def test_manifest_cannot_add_an_unrelated_path(prepared):
    server, bundle, _ = prepared
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside.py"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="five approved source paths"):
        bundle_tool.verify_bundle(server, bundle, "before")


def test_bundle_creation_cannot_overwrite_an_existing_artifact(prepared):
    _, _, archive = prepared
    original = archive.read_bytes()
    with pytest.raises(FileExistsError):
        bundle_tool.create_bundle(ROOT, archive)
    assert archive.read_bytes() == original
