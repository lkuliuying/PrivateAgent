"""阶段 D 准备：候选冻结与审阅缺证据时保持阻断。"""
import hashlib
import json
from argparse import Namespace

import pytest
import run_coding_acceptance as runner
from coding_acceptance_evidence import Evidence, digest, write_json
from coding_acceptance_review import review
from coding_acceptance_schema import fingerprint
from coding_acceptance_transport import Fixture, RuntimeClient, reply


def test_source_identity_includes_desktop_host_and_explicit_unknowns():
    identity = runner.product_identity(None)
    for name in ("apps/desktop/src/services/privateTransport.ts", "apps/exec-host/src/main.rs",
                 "apps/desktop/src-tauri/src/local_executor.rs"):
        assert name in identity["files"]
    assert identity["installation"]["status"] == "unknown"
    assert identity["running_process"]["status"] == "unknown"


def test_source_identity_survives_evidence_redaction_without_exposing_secrets(tmp_path):
    from coding_acceptance_identity import verify_current_product
    from coding_acceptance_schema import read_json

    identity = runner.product_identity(None)
    write_json(tmp_path / "identity.json", {"product": identity, "api_key": "synthetic-secret"})
    restored = read_json(tmp_path / "identity.json")
    assert restored["api_key"] == "[REDACTED]"
    assert restored["product"] == identity
    verify_current_product(restored["product"])


def test_empty_bundle_source_manifest_is_rejected(tmp_path):
    for name in ("private-agent-local.exe", "exec-host.exe"):
        (tmp_path / name).write_bytes(b"MZ-synthetic")
    (tmp_path / "exec-host.sha256").write_text(digest(tmp_path / "exec-host.exe"), encoding="ascii")
    write_json(tmp_path / "source-manifest.json", {"sources": []})
    write_json(tmp_path / "build-info.json", {})
    with pytest.raises(ValueError):
        runner.product_identity(tmp_path)


def test_product_change_after_preflight_prevents_first_attempt(tmp_path, monkeypatch):
    state = {"sha256": "before"}
    monkeypatch.setattr(runner, "product_identity", lambda _bundle: dict(state))

    def preflight(_tasks):
        state["sha256"] = "after"
        return {"passed": True, "missing": []}

    calls = []
    monkeypatch.setattr(runner, "preflight", preflight)
    monkeypatch.setattr(runner, "attempt", lambda *args, **kwargs: calls.append(True))
    assert runner.run(Namespace(mode="control", tasks="PY01", repetitions=1, protocol="service",
                                model_config=None, bundle=None, work_dir=tmp_path)) == 1
    assert not calls
    directory = next(tmp_path.glob("control-*"))
    assert (directory / "starts.jsonl").read_text() == ""


def review_fixture(tmp_path, extra_manifest=None):
    plan = {"attempt_id": "one", "task_id": "PY01", "mode": "quality", "model": "synthetic",
            "family": "python", "category": "bug", "split": "development", "coding_goal": True,
            "holdout_exposure": "public_calibration"}
    evidence = Evidence(tmp_path, {"mode": "quality", "schedule": [plan], "product": {},
                                   "statistics_version": "s6-attempt-ledger-1", **(extra_manifest or {})})
    evidence.start(plan)
    write_json(tmp_path / "artifacts/one.json", {"synthetic": True})
    hashes = {"artifacts/one.json": digest(tmp_path / "artifacts/one.json")}
    evidence.append({**plan, "started": True, "evidence_complete": True, "evidence_sha256": hashes,
                     "human_interventions": 0, "failure_class": "runtime_failed"})
    evidence.finish()
    receipt = {"manifest_sha256": digest(tmp_path / "manifest.json"),
               "attempts_sha256": digest(tmp_path / "attempts.jsonl"),
               "reviewer_role": "合成审阅测试", "reviewed_at": "2026-09-15T00:00:00+08:00",
               "attempts": [{"attempt_id": "one", "evidence_sha256": hashes, "report_matches_facts": True,
                             "human_interventions": 0, "constraints_satisfied": True, "note": "仅测试审阅结构。"}]}
    write_json(tmp_path / "receipt.json", receipt)
    return receipt


def test_review_preserves_incomplete_experiment_and_public_role(tmp_path):
    review_fixture(tmp_path)
    original = digest(tmp_path / "attempts.jsonl")
    result = json.loads((review(tmp_path, tmp_path / "receipt.json") / "metrics.json").read_text(encoding="utf-8"))
    assert result["experiment_complete"] is False
    assert result["delivery_decision"] == "blocked"
    assert result["models"]["synthetic"]["overall"]["independent_completed"] == 0
    assert digest(tmp_path / "attempts.jsonl") == original


def test_review_rejects_duplicate_json_fields(tmp_path):
    receipt = review_fixture(tmp_path)
    body = json.dumps(receipt, ensure_ascii=False)
    body = body.replace('"report_matches_facts": true', '"report_matches_facts": false, "report_matches_facts": true')
    (tmp_path / "receipt.json").write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        review(tmp_path, tmp_path / "receipt.json")


def test_review_recalculates_completeness_instead_of_trusting_summary(tmp_path):
    review_fixture(tmp_path)
    path = tmp_path / "metrics.json"
    metrics = json.loads(path.read_text(encoding="utf-8"))
    metrics["experiment_complete"] = True
    write_json(path, metrics)
    result = json.loads((review(tmp_path, tmp_path / "receipt.json") / "metrics.json").read_text(encoding="utf-8"))
    assert result["experiment_complete"] is False


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    import coding_acceptance_identity as identity

    source = tmp_path / "source"
    source.mkdir()
    names = ("src/private_agent_local/runtime.py", "apps/desktop/src/services/privateTransport.ts", "apps/exec-host/src/main.rs",
             "apps/desktop/src/api/modelSecrets.spec.ts")
    for name in names:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source", encoding="utf-8")
    monkeypatch.setattr(identity, "ROOT", source)
    monkeypatch.setattr(identity, "workspace_sources", lambda: {name: digest(source / name) for name in names})
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name in ("PrivateAgent-windows-x64.exe", "private-agent-local.exe", "exec-host.exe"):
        (bundle / name).write_bytes(b"MZ-synthetic")
    (bundle / "exec-host.sha256").write_text(digest(bundle / "exec-host.exe"), encoding="ascii")

    def manifest(entries=None):
        entries = entries if entries is not None else [{"path": name, "sha256": digest(source / name)} for name in names]
        sha = hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
        write_json(bundle / "source-manifest.json", {"sourceSha256": sha, "sources": entries})
        write_json(bundle / "build-info.json", {"unified": True, "sourceSha256": sha,
                   "executionHostSha256": digest(bundle / "exec-host.exe"), "sha256": digest(bundle / "PrivateAgent-windows-x64.exe")})
        return entries

    manifest()
    return identity, source, bundle, manifest


def test_candidate_artifacts_never_imply_installed_or_loaded(candidate):
    identity, _, bundle, _ = candidate
    result = identity.product_identity(bundle)
    assert result["source_matches"] is True
    assert result["build_artifacts"]["status"] == "hashed"
    assert result["installation"]["status"] == result["running_process"]["status"] == "unknown"
    assert result["build"]["version"] == "unknown"
    write_json(bundle / "identity.json", result)
    restored = json.loads((bundle / "identity.json").read_text(encoding="utf-8"))
    assert restored == result
    identity.verify_current_product(restored)


@pytest.mark.parametrize("component", ["PrivateAgent-windows-x64.exe", "exec-host.exe"])
def test_candidate_changed_binary_is_rejected(candidate, component):
    identity, _, bundle, _ = candidate
    (bundle / component).write_bytes(b"changed")
    with pytest.raises(ValueError, match="摘要"):
        identity.product_identity(bundle)


def test_candidate_missing_source_cannot_be_frozen(candidate):
    identity, _, bundle, manifest = candidate
    entries = manifest()
    manifest(entries[:-1])
    result = identity.product_identity(bundle)
    assert result["source_matches"] is False and result["source_missing"] == [entries[-1]["path"]]


def test_candidate_duplicate_source_is_rejected_even_with_updated_digest(candidate):
    identity, _, bundle, manifest = candidate
    entries = manifest()
    manifest([*entries, entries[0]])
    with pytest.raises(ValueError, match="重复"):
        identity.product_identity(bundle)


def test_changed_desktop_source_invalidates_old_evidence(candidate):
    identity, source, _, _ = candidate
    frozen = identity.product_identity(None)
    identity.verify_current_product(frozen)
    (source / "apps/desktop/src/services/privateTransport.ts").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="源码已变化"):
        identity.verify_current_product(frozen)


def test_review_rejects_changed_bundle(candidate, tmp_path):
    identity, _, bundle, _ = candidate
    directory = tmp_path / "evidence"
    directory.mkdir()
    review_fixture(directory, {"product": identity.product_identity(bundle), "bundle_path": str(bundle)})
    (bundle / "PrivateAgent-windows-x64.exe").write_bytes(b"changed")
    with pytest.raises(ValueError, match="摘要"):
        review(directory, directory / "receipt.json")


@pytest.mark.parametrize("changed", ["catalog", "runner", "config"])
def test_review_rejects_changed_frozen_inputs(tmp_path, monkeypatch, changed):
    import coding_acceptance_catalog as catalog
    import coding_acceptance_review as reviewer

    (tmp_path / "scripts").mkdir()
    judge = tmp_path / "scripts/judge.py"
    judge.write_text("synthetic judge", encoding="utf-8")
    config = tmp_path / "model.json"
    write_json(config, {"synthetic": True})
    current = {"catalog_sha256": "frozen"}
    monkeypatch.setattr(catalog, "load_catalog", lambda _: dict(current))
    monkeypatch.setattr(reviewer, "ROOT", tmp_path)
    monkeypatch.setattr(reviewer, "verify_current_product", lambda _: None)
    review_fixture(tmp_path, {"product": {"identity_version": "s6-product-2", "kind": "source"},
                             "catalog_sha256": "frozen", "runner_sha256": {"judge.py": digest(judge)},
                             "model_config_path": str(config), "model_config_sha256": digest(config)})
    assert (review(tmp_path, tmp_path / "receipt.json") / "metrics.json").is_file()
    if changed == "catalog":
        current["catalog_sha256"] = "changed"
    elif changed == "runner":
        judge.write_text("changed", encoding="utf-8")
    else:
        write_json(config, {"synthetic": False})
    with pytest.raises(ValueError, match="变化"):
        review(tmp_path, tmp_path / "receipt.json")


def test_rehashed_duplicate_attempt_is_rejected(tmp_path):
    from coding_acceptance_evidence import verify_ledger

    review_fixture(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    first = json.loads((tmp_path / "attempts.jsonl").read_text(encoding="utf-8"))
    second = {**first, "previous_record_sha256": first["record_sha256"]}
    second["record_sha256"] = fingerprint({key: value for key, value in second.items() if key != "record_sha256"})
    with pytest.raises(ValueError, match="重复"):
        verify_ledger(tmp_path, manifest, [first, second])


def test_actual_ipc_correlation_and_test_database_identity(tmp_path):
    with Fixture() as fixture, RuntimeClient(tmp_path, fixture) as client:
        client.request("/identity/local", "POST")
        project = tmp_path / "project"
        project.mkdir()
        created = client.request("/projects", "POST", {"name": "关联验证", "root_path": str(project)})
        workspace = client.request(f"/projects/{created['id']}/workspaces")[0]
        binding = {"project_id": created["id"], "workspace_id": workspace["id"]}
        session = client.request("/sessions", "POST", {**binding, "title": "合成"})
        fixture.responses.append(reply("只解释，不修改文件。"))
        run = client.request("/agent-runs", "POST", {**binding, "session_id": session["id"], "message": "只解释",
                             "permission_mode": "readonly", "client_request_id": "phase-d-correlation", "model_profile_id": client.fixture.profile_id})
        creation = next(row for row in client.request_correlations if row["path"] == "/agent-runs")
        assert creation["client_request_id"] == "phase-d-correlation"
        assert creation["result_ids"]["id"] == run["id"] and creation["response_received"]
        assert len({row["ipc_request_id"] for row in client.request_correlations}) == len(client.request_correlations)
        assert fixture.token not in json.dumps(client.request_correlations)
        observed = client.process_identity()
        assert observed["project_database_schemas"] == [7]
        assert observed["pid"] == client.process.pid and len(observed["launch_executable_sha256"]) == 64
        assert observed["loaded_component_attestation"] == "unknown"
