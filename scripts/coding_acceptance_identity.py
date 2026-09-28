"""复用 S6 清单记录候选来源；源码、产物、安装与进程证据分别判断。"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from coding_acceptance_evidence import digest
from coding_acceptance_schema import (
    fields,
    fingerprint,
    plain_path,
    read_json,
    safe_relative,
    sha256,
)
from run_coding_validation import ROOT

SOURCE_ROOTS = ("src/private_agent_core", "src/private_agent_local", "apps/desktop/src",
                "apps/desktop/src-tauri", "apps/exec-host")
BUILD_INPUTS = ("pyproject.toml", "requirements.txt", "apps/desktop/package.json", "apps/desktop/package-lock.json",
                "apps/desktop/index.html", "apps/desktop/vite.config.ts", "apps/desktop/tsconfig.json",
                "apps/desktop/tsconfig.node.json", "scripts/build-client.cjs", "scripts/build-remote-client.cjs")


def workspace_sources() -> dict[str, str]:
    result = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                             *SOURCE_ROOTS, *BUILD_INPUTS], cwd=ROOT, capture_output=True,
                            check=True, timeout=15)
    names = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    if not names:
        raise ValueError("候选源码集合为空")
    deleted = subprocess.run(["git", "ls-files", "-z", "--deleted", "--", *SOURCE_ROOTS, *BUILD_INPUTS],
                             cwd=ROOT, capture_output=True, check=True, timeout=15)
    removed = set(deleted.stdout.decode("utf-8").split("\0"))
    # 工作区已经删除的受跟踪文件不属于当前候选；其他缺失仍由 source_path 明确报错。
    return {name: digest(source_path(name)) for name in names if name not in removed}


def source_path(name: str) -> Path:
    safe_relative(name)
    if not (name.startswith(("src/", "apps/", "scripts/")) or name in {"pyproject.toml", "requirements.txt"}):
        raise ValueError("候选源码清单包含范围外路径")
    if any(part.startswith(".env") or part.lower().endswith((".pem", ".key"))
           or part in {"node_modules", "target", "__pycache__", ".git"} for part in name.split("/")):
        raise ValueError("候选源码清单包含敏感或生成路径")
    return plain_path(ROOT / name)


def source_mapping(entries: list) -> dict[str, str]:
    if not isinstance(entries, list) or not 1 <= len(entries) <= 20000:
        raise ValueError("候选源码清单为空或超过配额")
    declared, seen = {}, set()
    for entry in entries:
        fields(entry, {"path", "sha256"})
        source_path(entry["path"])
        sha256(entry["sha256"])
        if entry["path"].casefold() in seen:
            raise ValueError("候选源码清单包含重复路径")
        seen.add(entry["path"].casefold())
        declared[entry["path"]] = entry["sha256"]
    return declared


def source_fields(sources: dict[str, str]) -> dict:
    # 文件路径可能含 Secrets 等合法标识，不能作为通用脱敏器的字典字段名。
    return {"files": list(sources), "source_files": [{"path": name, "sha256": sha} for name, sha in sources.items()]}


def product_identity(bundle: Path | None) -> dict:
    sources = workspace_sources()
    components = {root: fingerprint({name: sha for name, sha in sources.items() if name.startswith(root + "/")})
                  for root in SOURCE_ROOTS}
    common = {"identity_version": "s6-product-2", "installed_desktop_verified": False,
              "installation": {"status": "unknown", "reason": "installation_not_inspected"},
              "running_process": {"status": "unknown", "reason": "record_separately_from_started_ipc_process"},
              "model_transport": "local_agent_direct_provider; api_key_only_local_session",
              "legacy_proxy_semantics": "removed; local_api_key_only"}
    if not bundle:
        # 保留旧 sha256 字段形状，但新版集合包含桌面、宿主与构建输入。
        return {**common, "kind": "source", **source_fields(sources), "components": components,
                "sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
                "build_artifacts": {"status": "unknown", "reason": "source_mode_does_not_identify_a_build"}}
    bundle = plain_path(bundle)
    source = read_json(bundle / "source-manifest.json")
    fields(source, {"sourceSha256", "sources"})
    entries = source["sources"]
    declared = source_mapping(entries)
    source_hash = hashlib.sha256(json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    if source["sourceSha256"] != source_hash:
        raise ValueError("候选源码清单总摘要不符")
    info = read_json(bundle / "build-info.json")
    if not isinstance(info, dict) or type(info.get("unified")) is not bool:
        raise ValueError("候选构建身份缺少客户端类型")
    desktop = "PrivateAgent-windows-x64.exe" if info["unified"] else "PrivateAgent-remote-windows-x64.exe"
    names = (desktop, "private-agent-local.exe", "exec-host.exe", "exec-host.sha256", "build-info.json", "source-manifest.json")
    artifacts = {name: digest(plain_path(bundle / name)) for name in names}
    if ((bundle / "exec-host.sha256").read_text(encoding="ascii").strip() != artifacts["exec-host.exe"]
            or info.get("executionHostSha256") != artifacts["exec-host.exe"]
            or info.get("sha256") != artifacts[desktop] or info.get("sourceSha256") != source_hash):
        raise ValueError("候选产物与构建记录摘要不符")
    missing = sorted(sources.keys() - declared.keys())
    mismatches = sorted(name for name, expected in declared.items() if digest(source_path(name)) != expected)
    return {**common, "kind": "bundle", "sha256": artifacts, "source_mismatches": mismatches,
            "source_missing": missing, "source_matches": not mismatches and not missing,
            "source_sha256": source_hash, **source_fields(declared),
            "components": {root: fingerprint({name: sha for name, sha in declared.items() if name.startswith(root + "/")})
                           for root in SOURCE_ROOTS},
            "build_artifacts": {"status": "hashed", "files": artifacts,
                                "reason": "local_artifacts_only; not_installation_or_loaded_memory"},
            "build": {key: info.get(key, "unknown") for key in
                      ("commit", "dirty", "version", "target", "transport", "signing", "mode", "qa", "applicationIdentifier")}}


def verify_current_product(identity: dict) -> None:
    """新记录审阅时核对当前源码；历史记录只作历史解释，不补造安装证明。"""
    if identity.get("identity_version") != "s6-product-2":
        return
    current = workspace_sources()
    declared = source_mapping(identity["source_files"])
    if identity["files"] != list(declared):
        raise ValueError("候选源码索引与摘要清单不一致")
    if any(name not in declared or declared[name] != sha for name, sha in current.items()):
        raise ValueError("产品源码已变化，原证据不能用于当前候选")
    if any(digest(source_path(name)) != sha for name, sha in declared.items()):
        raise ValueError("产品源码已变化，原证据不能用于当前候选")
