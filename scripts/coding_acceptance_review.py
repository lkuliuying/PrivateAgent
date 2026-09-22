"""对已冻结证据追加人工事实审阅；不改写尝试、模型结果或实验分母。"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path, PurePosixPath

from coding_acceptance_evidence import (
    aggregate,
    digest,
    experiment_status,
    verify_ledger,
    write_json,
)
from coding_acceptance_identity import product_identity, verify_current_product
from coding_acceptance_schema import plain_path, read_json, safe_relative, strict_json
from run_coding_validation import ROOT, new_directory


def review(evidence: Path, reviews: Path) -> Path:
    evidence = plain_path(evidence)
    manifest_path = evidence / "manifest.json"
    attempts_path = evidence / "attempts.jsonl"
    for path in (manifest_path, attempts_path, reviews):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("审阅输入不是有界普通文件")
    manifest = read_json(manifest_path)
    attempts = [strict_json(line) for line in attempts_path.read_text(encoding="utf-8").splitlines()]
    verify_ledger(evidence, manifest, attempts)
    verify_current_product(manifest.get("product", {}))
    if manifest.get("product", {}).get("identity_version") == "s6-product-2":
        from coding_acceptance_catalog import load_catalog

        if manifest["product"].get("kind") == "bundle":
            if not manifest.get("bundle_path") or product_identity(Path(manifest["bundle_path"])) != manifest["product"]:
                raise ValueError("候选构建产物已变化或无法核对")
        catalog = load_catalog(Path(manifest["catalog_path"]) if manifest.get("catalog_path") else None)
        if catalog["catalog_sha256"] != manifest["catalog_sha256"]:
            raise ValueError("题集或判定材料已变化")
        for name, expected in manifest["runner_sha256"].items():
            safe_relative(name)
            if "/" in name or digest(plain_path(ROOT / "scripts" / name)) != expected:
                raise ValueError("运行器或判定器已变化")
        if manifest.get("model_config_path") and digest(plain_path(Path(manifest["model_config_path"]))) != manifest["model_config_sha256"]:
            raise ValueError("模型配置已变化")
    receipts = read_json(reviews)
    if set(receipts) != {"manifest_sha256", "attempts_sha256", "reviewer_role", "reviewed_at", "attempts"}:
        raise ValueError("审阅字段不符合协议")
    if receipts["manifest_sha256"] != digest(manifest_path) or receipts["attempts_sha256"] != digest(attempts_path):
        raise ValueError("审阅对应的实验已经变化")
    stamp = datetime.fromisoformat(receipts["reviewed_at"])
    if stamp.utcoffset() is None or not isinstance(receipts["reviewer_role"], str) or not receipts["reviewer_role"].strip():
        raise ValueError("审阅缺少时区或责任角色")
    index = {row["attempt_id"]: row for row in attempts}
    seen = set()
    for receipt in receipts["attempts"]:
        if set(receipt) != {"attempt_id", "evidence_sha256", "report_matches_facts", "human_interventions", "constraints_satisfied", "note"}:
            raise ValueError("逐次审阅字段不符")
        identity = receipt["attempt_id"]
        if identity in seen or identity not in index:
            raise ValueError("审阅包含重复或不存在的尝试")
        seen.add(identity)
        row = index[identity]
        if row.get("evidence_complete") is not True or not row.get("evidence_sha256") or receipt["evidence_sha256"] != row["evidence_sha256"]:
            raise ValueError("缺少完整证据，或审阅摘要不匹配")
        for name, expected in row["evidence_sha256"].items():
            relative = PurePosixPath(name)
            safe_relative(name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
                raise ValueError("证据引用越界")
            path = plain_path(evidence / name)
            if path.is_symlink() or not path.resolve().is_relative_to(evidence) or digest(path) != expected:
                raise ValueError("证据已改变或越界")
            if name.startswith("artifacts/") and name.endswith(".json") and row.get("binding"):
                artifact = read_json(path)
                if artifact.get("binding") != row["binding"] or artifact.get("candidate_sha256") != row.get("candidate_sha256"):
                    raise ValueError("候选产物与尝试绑定不符")
        if (type(receipt["human_interventions"]) is not int or receipt["human_interventions"] < row.get("human_interventions", 0)
                or type(receipt["report_matches_facts"]) is not bool or type(receipt["constraints_satisfied"]) is not bool
                or not isinstance(receipt["note"], str) or not receipt["note"].strip() or len(receipt["note"]) > 2000):
            raise ValueError("审阅事实、人工次数或说明无效")
        row.update(report_matches_facts=receipt["report_matches_facts"], human_interventions=receipt["human_interventions"],
                   reviewed_constraints=receipt["constraints_satisfied"])
    original_metrics = read_json(evidence / "metrics.json")
    metrics = aggregate(attempts, manifest["schedule"], runner_errors=original_metrics["runner_errors"])
    metrics.update(experiment_status(attempts, manifest, metrics))
    metrics.update(delivery_decision="blocked", reason="人工审阅不能解除题集污染、隔离缺证据或尚未执行的桌面与安装门禁",
                   reviewed_attempts=sorted(seen), reviewer_role=receipts["reviewer_role"], reviewed_at=receipts["reviewed_at"],
                   source_manifest_sha256=digest(manifest_path), source_attempts_sha256=digest(attempts_path))
    destination = new_directory(evidence, "review")
    write_json(destination / "review.json", receipts)
    write_json(destination / "metrics.json", metrics)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(review(args.evidence, args.reviews))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("审阅拒绝：" + type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
