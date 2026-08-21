"""v0.7.0 E2：项目命令与结果解析测试。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md`` §6。

覆盖 E2 范围与测试矩阵：
- 11 种结果解析器（pytest/ruff/mypy/compileall/npm_test/npm_build/npm_lint/
  vue_tsc/cargo_test/cargo_check/plain）单元解析 + 有界截断；
- profile 字段校验（cwd_rel/env_allowlist/result_parser/risk_level/
  max_output_bytes，非法抛 ValueError，API 映射 422）；
- profile CRUD + 版本递增（update 即 profile_version+1，历史快照不变）；
- _resolve_command 落地 cwd_rel / env_allowlist / max_output_bytes /
  result_parser；非白名单 argv 仍拒绝；
- run_whitelisted_command_trusted 输出附加 profile_version + parsed；
- 每次 coding run 快照 command_profile_version（E0 §6）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete

from personal_assistant.agents import (
    CancellationToken,
)
from personal_assistant.core.command_workflow import (
    _resolve_command,
    run_whitelisted_command_trusted,
)
from personal_assistant.core.models import (
    AgentRun as AgentRunRecord,
)
from personal_assistant.core.models import Project, ProjectWorkspace
from personal_assistant.core.patch_sets import (
    CommandProfileService,
    _validate_profile_fields,
)
from personal_assistant.core.result_parsers import (
    MAX_FAILURE_ENTRIES,
    RESULT_PARSERS,
    parse_command_result,
)

# ===========================================================================
# §6：结果解析器单元测试（11 种）
# ===========================================================================


def test_parsers_enum_frozen():
    assert RESULT_PARSERS == {
        "pytest",
        "ruff",
        "mypy",
        "compileall",
        "npm_test",
        "npm_build",
        "npm_lint",
        "vue_tsc",
        "cargo_test",
        "cargo_check",
        "plain",
    }


def test_parse_pytest_stats_and_failures():
    out = (
        "tests/test_a.py::test_ok PASSED\n"
        "FAILED tests/test_a.py::test_bad - AssertionError: boom\n"
        "============================= 8 passed, 1 failed in 1.23s =============================\n"
    )
    r = parse_command_result("pytest", out)
    assert r["parser"] == "pytest"
    assert r["passed"] == 8
    assert r["failed"] == 1
    assert r["summary"] == "8 passed, 1 failed in 1.23s"
    assert r["failures"] == [
        {
            "message": "AssertionError: boom",
            "file": "tests/test_a.py::test_bad",
        }
    ]
    assert r["truncated"] is False


def test_parse_pytest_failure_cap_50():
    lines = [f"FAILED tests/t{i}.py::t - m{i}" for i in range(70)]
    r = parse_command_result("pytest", "\n".join(lines))
    assert len(r["failures"]) == MAX_FAILURE_ENTRIES
    assert r["truncated"] is True


def test_parse_ruff_items_and_counts():
    out = (
        "src/a.py:1:5: F401 `os` imported but unused\n"
        "src/b.py:2:9: E501 line too long\n"
        "Found 2 errors.\n"
    )
    r = parse_command_result("ruff", out)
    assert r["errors"] == 2
    assert r["summary"] == "2 errors"
    assert r["failures"][0] == {
        "message": "`os` imported but unused",
        "file": "src/a.py",
        "line": 1,
        "column": 5,
        "code": "F401",
    }


def test_parse_mypy_errors():
    out = (
        "src/a.py:3: error: Incompatible types (assignment)\n"
        "src/b.py:4: error: Name 'x' is not defined  [name-defined]\n"
        "Found 2 errors in 2 files (checked 5 source files)\n"
    )
    r = parse_command_result("mypy", out)
    assert r["errors"] == 2
    # 无 code 后缀的行不产出 code 字段
    assert r["failures"][0]["file"] == "src/a.py"
    assert "code" not in r["failures"][0]
    assert r["failures"][1]["code"] == "name-defined"
    assert "Found 2 errors in 2 files" in r["summary"]


def test_parse_compileall_success_and_error():
    ok = parse_command_result("compileall", "Compiling 'src/a.py'...\n")
    assert ok["errors"] == 0
    assert "全部编译成功" in ok["summary"]
    bad = parse_command_result(
        "compileall", "src/a.py: Error: invalid syntax (a.py, line 3)\n"
    )
    assert bad["errors"] == 1
    assert bad["failures"][0]["file"] == "src/a.py"


def test_parse_npm_test_jest():
    out = (
        "FAIL src/a.test.ts\n"
        "Tests: 2 failed, 10 passed, 12 total\n"
        "npm ERR! Test failed.  See above for more details.\n"
    )
    r = parse_command_result("npm_test", out)
    assert r["passed"] == 10
    assert r["failed"] == 2
    assert r["summary"] == "Tests: 2 failed, 10 passed"
    assert r["failures"][0]["file"] == "src/a.test.ts"


def test_parse_npm_build_tsc_errors():
    out = (
        "src/a.ts:5:3: error TS2322: Type 'string' is not assignable to type 'number'.\n"
        "npm ERR! build failed\n"
    )
    r = parse_command_result("npm_build", out)
    assert r["errors"] >= 1
    assert r["failures"][0]["line"] == 5
    assert r["failures"][0]["message"].startswith("Type 'string'")


def test_parse_npm_lint_eslint():
    out = (
        "src/a.ts:1:5  no-unused-vars  'x' is defined but never used\n"
        "src/a.ts:2:9  semi  Missing semicolon\n"
        "2 problems (2 errors, 0 warnings)\n"
    )
    r = parse_command_result("npm_lint", out)
    assert r["errors"] == 2
    assert r["warnings"] == 0
    assert len(r["failures"]) == 2
    assert r["failures"][0]["code"] == "no-unused-vars"


def test_parse_vue_tsc():
    out = (
        "src/App.vue(12,8): error TS2339: Property 'x' does not exist on type '{}'.\n"
        "Found 1 error.\n"
    )
    r = parse_command_result("vue_tsc", out)
    assert r["errors"] == 1
    assert r["failures"][0]["file"] == "src/App.vue"
    assert r["failures"][0]["line"] == 12
    assert r["failures"][0]["code"] == "TS2339"


def test_parse_cargo_test_result():
    out = (
        "test result: FAILED. 7 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out\n"
        "error[E0308]: mismatched types\n"
        "  --> src/lib.rs:10:5\n"
    )
    r = parse_command_result("cargo_test", out)
    assert r["passed"] == 7
    assert r["failed"] == 2
    assert r["failures"][0] == {
        "message": "mismatched types",
        "file": "src/lib.rs",
        "line": 10,
        "column": 5,
        "code": "E0308",
    }


def test_parse_cargo_check_clean():
    r = parse_command_result("cargo_check", "    Checking hello v0.1.0\nFinished\n")
    assert r["errors"] == 0
    assert "未发现编译错误" in r["summary"]


def test_parse_plain_fallback_and_unknown():
    r = parse_command_result("plain", "hello world")
    assert r["parser"] == "plain"
    assert r["summary"] == "hello world"
    # 未知 parser 回落 plain
    unknown = parse_command_result("not-a-parser", "x")
    assert unknown["parser"] == "plain"


def test_parse_bounds_fields():
    r = parse_command_result("pytest", "FAILED f - " + "m" * 5000)
    assert len(r["failures"][0]["message"]) <= 4000


# ===========================================================================
# §6：profile 字段校验
# ===========================================================================


def test_validate_profile_fields_rejects_bad_cwd_rel():
    for bad in ("/abs/path", "C:\\abs", "\\\\server\\share", "../escape", "a/../../b"):
        with pytest.raises(ValueError, match="cwd_rel"):
            _validate_profile_fields(cwd_rel=bad)
    # 合法：空 / 根内相对
    _validate_profile_fields(cwd_rel="")
    _validate_profile_fields(cwd_rel="sub/dir")
    _validate_profile_fields(cwd_rel=".")


def test_validate_profile_fields_rejects_bad_env_allowlist():
    with pytest.raises(ValueError, match="字符串数组"):
        _validate_profile_fields(env_allowlist=["PATH", 3])
    with pytest.raises(ValueError, match="有效环境变量名"):
        _validate_profile_fields(env_allowlist=["A=B"])
    with pytest.raises(ValueError, match="代理/凭据类"):
        _validate_profile_fields(env_allowlist=["API_KEY"])
    with pytest.raises(ValueError, match="代理/凭据类"):
        _validate_profile_fields(env_allowlist=["HTTP_PROXY"])
    _validate_profile_fields(env_allowlist=["PA_E2_TEST_VAR"])


def test_validate_profile_fields_rejects_bad_parser_risk_and_bytes():
    with pytest.raises(ValueError, match="result_parser"):
        _validate_profile_fields(result_parser="nosuch")
    with pytest.raises(ValueError, match="risk_level"):
        _validate_profile_fields(risk_level="root")
    for bad in (0, -1, 10 * 1024 * 1024 + 1, True, "100"):
        with pytest.raises(ValueError, match="max_output_bytes"):
            _validate_profile_fields(max_output_bytes=bad)  # type: ignore[arg-type]
    _validate_profile_fields(max_output_bytes=1024)


# ===========================================================================
# §6：profile CRUD + 版本递增
# ===========================================================================


async def _make_project(db, tmp_path: Path) -> tuple[int, int]:
    project = Project(name=f"e2-cmd-{uuid4().hex[:8]}", root_path=str(tmp_path))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    workspace = ProjectWorkspace(
        project_id=project.id,
        kind="root",
        root_path=str(tmp_path),
        root_path_sha256="a" * 64,
        status="active",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return project.id, workspace.id


async def test_command_profile_crud_and_version_increment(db, tmp_path):
    from personal_assistant.core.models import ProjectCommandProfile

    project_id, workspace_id = await _make_project(db, tmp_path)
    svc = CommandProfileService(db)
    p = await svc.create(
        project_id=project_id,
        name="pytest-e2e",
        command_json={"args": [sys.executable, "-m", "pytest"]},
        kind="test",
        timeout_seconds=60,
        cwd_rel="tests",
        env_allowlist=["PA_E2_TEST_VAR"],
        result_parser="pytest",
        risk_level="confirm",
        capability="run-tests",
        max_output_bytes=4096,
        description="E2 测试 profile",
    )
    assert p.profile_version == 1
    assert p.cwd_rel == "tests"
    assert p.env_allowlist == ["PA_E2_TEST_VAR"]
    assert p.result_parser == "pytest"
    assert p.risk_level == "confirm"
    assert p.max_output_bytes == 4096

    # 内容变更 → 版本递增；历史 run 快照不受影响（快照在别处断言）
    updated = await svc.update(p.id, description="E2 更新")
    assert updated.profile_version == 2

    # 非法更新 → ValueError，版本不递增
    with pytest.raises(ValueError, match="cwd_rel"):
        await svc.update(p.id, cwd_rel="/etc")
    fresh = await svc.repo.get(p.id)
    assert fresh is not None
    assert fresh.profile_version == 2

    # list + delete
    listed = await svc.list_by_project(project_id)
    assert any(x.id == p.id for x in listed)
    await svc.delete(p.id)
    assert await svc.repo.get(p.id) is None

    # 清理
    from sqlalchemy import delete as _del

    await db.execute(_del(ProjectCommandProfile).where(ProjectCommandProfile.project_id == project_id))
    await db.execute(_del(ProjectWorkspace).where(ProjectWorkspace.id == workspace_id))
    await db.execute(_del(Project).where(Project.id == project_id))
    await db.commit()


# ===========================================================================
# §6：_resolve_command 落地（cwd_rel / env_allowlist / 拒绝语义）
# ===========================================================================


async def test_resolve_command_applies_profile_constraints(db, tmp_path, monkeypatch):
    from personal_assistant.core.models import ProjectCommandProfile

    project_id, workspace_id = await _make_project(db, tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    monkeypatch.setenv("PA_E2_TEST_VAR", "hello-e2")
    profile = ProjectCommandProfile(
        project_id=project_id,
        name="py-cmd",
        command_json={"args": [sys.executable, "-c"]},
        kind="custom",
        timeout_seconds=30,
        enabled=True,
        profile_version=1,
        cwd_rel="sub",
        env_allowlist=["PA_E2_TEST_VAR"],
        result_parser="plain",
        max_output_bytes=2048,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    args = [sys.executable, "-c", "print(1)"]
    resolved = await _resolve_command(db, project_id, args, timeout=None)
    assert resolved.matched_profile_name == "py-cmd"
    assert resolved.profile_version == 1
    assert resolved.result_parser == "plain"
    assert resolved.max_output_bytes == 2048
    assert Path(resolved.cwd).resolve() == sub.resolve()
    assert resolved.env.get("PA_E2_TEST_VAR") == "hello-e2"
    # 环境仍拒绝凭据类
    assert not any(
        "PROXY" in k or "SECRET" in k for k in resolved.env
    )

    # 非白名单且无 profile 前缀 → 拒绝
    from personal_assistant.core.permissions import PermissionError_

    with pytest.raises(PermissionError_):
        await _resolve_command(db, project_id, ["evil.exe", "--rm"], timeout=None)

    # cwd_rel 越界旧数据 → 执行时拒绝
    bad = ProjectCommandProfile(
        project_id=project_id,
        name="bad-cwd",
        command_json={"args": ["echo", "hi"]},
        kind="custom",
        timeout_seconds=30,
        enabled=True,
        cwd_rel="../../escape",
    )
    db.add(bad)
    await db.commit()
    with pytest.raises(PermissionError_):
        await _resolve_command(db, project_id, ["echo", "hi"], timeout=None)

    from sqlalchemy import delete as _del

    await db.execute(_del(ProjectCommandProfile).where(ProjectCommandProfile.project_id == project_id))
    await db.execute(_del(ProjectWorkspace).where(ProjectWorkspace.id == workspace_id))
    await db.execute(_del(Project).where(Project.id == project_id))
    await db.commit()


async def test_run_whitelisted_command_trusted_adds_parsed(db, tmp_path):
    """执行真实命令：输出含 profile_version + parsed（结构化解析结果）。"""
    from personal_assistant.core.models import ProjectCommandProfile

    project_id, workspace_id = await _make_project(db, tmp_path)
    profile = ProjectCommandProfile(
        project_id=project_id,
        name="py-e2e",
        command_json={"args": [sys.executable, "-c"]},
        kind="custom",
        timeout_seconds=30,
        enabled=True,
        result_parser="plain",
        max_output_bytes=4096,
    )
    db.add(profile)
    await db.commit()

    result = await run_whitelisted_command_trusted(
        db,
        project_id,
        [sys.executable, "-c", "print('E2-OK')"],
        timeout=30,
        cancellation=CancellationToken(),
    )
    assert result["succeeded"] is True
    assert result["profile"] == "py-e2e"
    assert result["profile_version"] == 1
    assert result["parsed"]["parser"] == "plain"
    assert "E2-OK" in result["parsed"]["summary"]
    assert result["processes_remaining"] == 0

    from sqlalchemy import delete as _del

    await db.execute(_del(ProjectCommandProfile).where(ProjectCommandProfile.project_id == project_id))
    await db.execute(_del(ProjectWorkspace).where(ProjectWorkspace.id == workspace_id))
    await db.execute(_del(Project).where(Project.id == project_id))
    await db.commit()


# ===========================================================================
# §6：API 错误映射（command_profile_invalid 422）
# ===========================================================================


async def test_api_command_profile_invalid_422(client, tmp_path):

    # 仅 project API 需要（commands 路由无 flag 门禁）
    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project = await client.post("/projects", json={"name": "e2-api", "root_path": root})
    project_id = project.json()["id"]

    base = {
        "name": "bad-profile",
        "command_json": {"args": [sys.executable, "-c"]},
        "kind": "custom",
    }
    # 非法 result_parser → 422
    resp = await client.post(
        f"/projects/{project_id}/commands", json={**base, "result_parser": "nosuch"}
    )
    assert resp.status_code == 422, resp.text
    # 非法 cwd_rel → 422
    resp = await client.post(
        f"/projects/{project_id}/commands", json={**base, "cwd_rel": "C:\\abs"}
    )
    assert resp.status_code == 422, resp.text
    # 敏感 env_allowlist → 422
    resp = await client.post(
        f"/projects/{project_id}/commands", json={**base, "env_allowlist": ["API_KEY"]}
    )
    assert resp.status_code == 422, resp.text
    # 合法创建 → 201，含 profile_version=1
    resp = await client.post(
        f"/projects/{project_id}/commands",
        json={**base, "result_parser": "pytest", "risk_level": "safe"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["profile_version"] == 1
    assert body["result_parser"] == "pytest"
    # PATCH 非法 → 422，版本不递增
    resp = await client.patch(
        f"/projects/{project_id}/commands/{body['id']}",
        json={"risk_level": "root"},
    )
    assert resp.status_code == 422, resp.text

    from sqlalchemy import delete as _del

    from personal_assistant.core.models import (
        Project,
        ProjectCommandProfile,
        ProjectWorkspace,
    )

    async with _factory_session() as s:
        await s.execute(
            _del(ProjectCommandProfile).where(ProjectCommandProfile.project_id == project_id)
        )
        await s.execute(_del(ProjectWorkspace).where(ProjectWorkspace.project_id == project_id))
        await s.execute(_del(Project).where(Project.id == project_id))
        await s.commit()


def _factory_session():
    """client fixture 重绑的测试库 factory（见 test_v070_patchset._run_events）。"""
    from personal_assistant.core.db import async_session_factory

    return async_session_factory()


# ===========================================================================
# §6：每次 coding run 快照 command_profile_version
# ===========================================================================


@pytest.fixture(autouse=True)
def _inject_immediate_model():
    """注入立即完成的模型，避免触发真实模型调用与长时间后台任务。"""
    from personal_assistant.agents.contracts import ModelResponse, TokenUsage
    from personal_assistant.api.routes_agent_runs import get_agent_model_client
    from personal_assistant.main_api import app

    class _ImmediateModel:
        async def complete(self, request, *, cancellation):
            del request, cancellation
            return ModelResponse(
                text="E2 测试回答",
                usage=TokenUsage(input_tokens=4, output_tokens=2, cached_tokens=0),
                provider="fake",
                model="fake-model",
                request_id="fake-request",
                latency_ms=0.5,
            )

    app.dependency_overrides[get_agent_model_client] = lambda: _ImmediateModel()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_agent_model_client, None)


async def test_run_snapshot_contains_command_profile_version(client, monkeypatch, tmp_path):
    """E0 §6：每次 coding run 快照记录 command profile 版本（取最高版本）。"""
    from personal_assistant.config import settings

    monkeypatch.setattr(settings, "agent_runs_api_enabled", True)
    monkeypatch.setattr(settings, "project_bound_runs_enabled", True)

    root = str((tmp_path / "p").resolve())
    (tmp_path / "p").mkdir()
    project = await client.post("/projects", json={"name": "e2-snap", "root_path": root})
    project_id = project.json()["id"]
    ws = await client.post(f"/projects/{project_id}/workspaces/root/ensure")
    ws_id = ws.json()["id"]
    session = await client.post(
        "/sessions",
        json={
            "title": "e2-snap",
            "project_id": project_id,
            "workspace_id": ws_id,
            "kind": "coding",
        },
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]

    base = {
        "name": "snap-profile",
        "command_json": {"args": [sys.executable, "-c"]},
        "kind": "custom",
    }
    p1 = await client.post(f"/projects/{project_id}/commands", json={**base, "name": "p-a"})
    p2 = await client.post(f"/projects/{project_id}/commands", json={**base, "name": "p-b"})
    assert p1.status_code == 201 and p2.status_code == 201
    p1_id = p1.json()["id"]
    # 更新 p-a → 版本 2；最高版本 = 2
    upd = await client.patch(
        f"/projects/{project_id}/commands/{p1_id}", json={"description": "v2"}
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["profile_version"] == 2

    resp = await client.post(
        "/agent-runs",
        json={
            "session_id": session_id,
            "message": "snapshot-test",
            "project_id": project_id,
            "workspace_id": ws_id,
            "permission_mode": "confirm",
            "client_request_id": str(uuid4()),
        },
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]

    # 经 client fixture 重绑的 factory 用独立 session 读快照（REPEATABLE READ 隔离）
    from personal_assistant.agents.repository import AgentRunRepository as Repo

    async with _factory_session() as s:
        run = await Repo(s).get_run(run_id)
        assert run is not None
        assert run.permission_snapshot_json is not None
        # E4：快照键契约为 permission_mode（不是 v0.6.0 时期的 mode）
        assert run.permission_snapshot_json["permission_mode"] == "confirm"
        assert run.permission_snapshot_json["command_profile_version"] == 2

    # 清理
    async with _factory_session() as s:
        from personal_assistant.core.models import (
            Project,
            ProjectCommandProfile,
            ProjectWorkspace,
        )

        await s.execute(
            delete(ProjectCommandProfile).where(ProjectCommandProfile.project_id == project_id)
        )
        await s.execute(delete(AgentRunRecord).where(AgentRunRecord.id == run_id))
        await s.execute(
            delete(ProjectWorkspace).where(ProjectWorkspace.project_id == project_id)
        )
        await s.execute(delete(Project).where(Project.id == project_id))
        await s.commit()
