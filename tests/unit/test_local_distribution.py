"""本机交付不得重新引入旧服务器、ORM 或部署入口。"""
import ast
import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from generate_release_manifest import build_manifest

ROOT = Path(__file__).resolve().parents[2]


def test_local_packages_are_independent_of_retired_server():
    forbidden = {"personal_assistant", "sqlalchemy", "alembic", "aiomysql", "langchain", "chromadb"}
    for package in ("private_agent_core", "private_agent_local"):
        for path in (ROOT / "src" / package).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                imports = [item.name for item in node.names] if isinstance(node, ast.Import) else (
                    [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                assert not {name.split(".")[0] for name in imports} & forbidden, path
    assert not (ROOT / "src/personal_assistant").exists()
    assert not (ROOT / "src/private_agent_local/cloud.py").exists()
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/private_agent_core", "src/private_agent_local"]
    for dependency in manifest["project"]["dependencies"]:
        assert not any(dependency.startswith(name) for name in forbidden)


def test_default_desktop_cannot_launch_old_server_or_use_its_update_channel():
    config = json.loads((ROOT / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    assert config["bundle"]["externalBin"] == []
    assert config["plugins"]["updater"]["endpoints"] == []
    native = (ROOT / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    assert "SidecarState" not in native and "start_sidecar" not in native
    assert "local_executor::start_local_executor" in native


def test_release_manifest_requires_complete_local_artifacts_and_matching_hashes(tmp_path):
    artifacts = {"PrivateAgent-windows-x64.exe": b"client", "private-agent-local.exe": b"local", "exec-host.exe": b"host"}
    for name, content in artifacts.items():
        (tmp_path / name).write_bytes(content)
    sources = [{"path": "src/private_agent_local/entry.py", "sha256": "a" * 64}]
    source_hash = hashlib.sha256(json.dumps(sources, separators=(",", ":")).encode()).hexdigest()
    host_hash = hashlib.sha256(b"host").hexdigest()
    (tmp_path / "exec-host.sha256").write_text(host_hash, encoding="utf-8")
    (tmp_path / "source-manifest.json").write_text(json.dumps({"sources": sources, "sourceSha256": source_hash}), encoding="utf-8")
    info = {"version": "1.0.0", "accessMode": "api-key", "sidecar": "desktop-local", "transport": "stdio-v2", "unified": True,
            "sourceSha256": source_hash, "executionHostSha256": host_hash, "sha256": hashlib.sha256(b"client").hexdigest()}
    (tmp_path / "build-info.json").write_text(json.dumps(info), encoding="utf-8")
    version, manifest = build_manifest(tmp_path)
    assert version == "1.0.0" and "private-agent-local.exe" in manifest
    assert "不声明单元测试" in manifest
    (tmp_path / "exec-host.exe").write_bytes(b"modified")
    with pytest.raises(ValueError, match="执行宿主"):
        build_manifest(tmp_path)
