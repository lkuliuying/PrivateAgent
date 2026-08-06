"""第四阶段 M4 测试：编码工作流（多文件 patch set + 项目命令配置 + 诊断）。

覆盖：命令配置 CRUD、运行配置命令（mock _execute_command）、patch set 创建/应用/回滚、
sha256 守卫（快照后改动拒绝应用）、created 文件回滚删除、命令失败诊断（mock LLM）。
项目经 POST /projects 建立（同步 trusted_paths），文件写真实 tmp_path 验证写入/回滚。
"""
from __future__ import annotations

import json

import pytest

from personal_assistant.core.provider import OllamaProvider

# ============ helpers ============


def _mock_chat(monkeypatch, payload) -> None:
    text = (
        json.dumps(payload, ensure_ascii=False)
        if isinstance(payload, (list, dict))
        else payload
    )

    async def fake_chat(self, messages):
        return text

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)


async def _project(client, tmp_path, name: str = "m4proj") -> tuple[int, object]:

    root = tmp_path / name
    root.mkdir()
    (root / "a.py").write_text("def v():\n    return 1\n", encoding="utf-8")
    res = await client.post("/projects", json={"name": name, "root_path": str(root)})
    assert res.status_code == 201, res.text
    return res.json()["id"], root


# ============ 命令配置 CRUD ============


@pytest.mark.asyncio
async def test_command_profile_crud(client, tmp_path):
    pid, _ = await _project(client, tmp_path)
    res = await client.post(
        f"/projects/{pid}/commands",
        json={"name": "跑测试", "command_json": {"command": "pytest -q"}, "kind": "test"},
    )
    assert res.status_code == 201, res.text
    cid = res.json()["id"]
    assert res.json()["kind"] == "test"

    res = await client.get(f"/projects/{pid}/commands")
    assert any(c["id"] == cid for c in res.json())

    res = await client.patch(
        f"/projects/{pid}/commands/{cid}", json={"enabled": False, "name": "测试改"}
    )
    assert res.status_code == 200
    assert res.json()["enabled"] is False
    assert res.json()["name"] == "测试改"

    res = await client.delete(f"/projects/{pid}/commands/{cid}")
    assert res.status_code == 200
    assert not any(
        c["id"] == cid for c in (await client.get(f"/projects/{pid}/commands")).json()
    )


# ============ 运行配置命令（mock 执行）============


@pytest.mark.asyncio
async def test_run_project_command(client, tmp_path, monkeypatch):
    pid, _ = await _project(client, tmp_path)
    cid = (
        await client.post(
            f"/projects/{pid}/commands",
            json={"name": "测试", "command_json": {"command": "pytest -q"}, "kind": "test"},
        )
    ).json()["id"]

    async def fake_exec(args, cwd, *, timeout=120):
        return {
            "args": args,
            "cwd": cwd,
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
            "output": "ok",
            "truncated": False,
            "succeeded": True,
        }

    monkeypatch.setattr("personal_assistant.core.patch_sets._execute_command", fake_exec)

    res = await client.post(f"/projects/{pid}/commands/{cid}/run")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["succeeded"] is True
    assert body["profile_id"] == cid
    assert body["args"] == ["pytest", "-q"]


# ============ patch set 应用 / 回滚 ============


@pytest.mark.asyncio
async def test_patch_set_apply_rollback(client, tmp_path):
    pid, root = await _project(client, tmp_path)
    res = await client.post(
        f"/projects/{pid}/patch-sets",
        json={
            "title": "改 a.py",
            "files": [{"rel_path": "a.py", "new_content": "def v():\n    return 2\n"}],
        },
    )
    assert res.status_code == 201, res.text
    ps = res.json()
    psid = ps["id"]
    assert ps["status"] == "draft"
    assert len(ps["files"]) == 1
    assert "return 2" in ps["files"][0]["diff_text"]

    # 应用前文件未变
    assert "return 1" in (root / "a.py").read_text(encoding="utf-8")
    res = await client.post(f"/patch-sets/{psid}/apply")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "applied"
    assert "return 2" in (root / "a.py").read_text(encoding="utf-8")

    # 回滚恢复旧内容
    res = await client.post(f"/patch-sets/{psid}/rollback")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "rolled_back"
    assert "return 1" in (root / "a.py").read_text(encoding="utf-8")


# ============ sha256 守卫 ============


@pytest.mark.asyncio
async def test_patch_set_sha_guard(client, tmp_path):
    pid, root = await _project(client, tmp_path)
    psid = (
        await client.post(
            f"/projects/{pid}/patch-sets",
            json={
                "title": "改 a.py",
                "files": [{"rel_path": "a.py", "new_content": "def v():\n    return 2\n"}],
            },
        )
    ).json()["id"]
    # 快照后外部修改文件 → apply 应 409
    (root / "a.py").write_text("def v():\n    return 99\n", encoding="utf-8")
    res = await client.post(f"/patch-sets/{psid}/apply")
    assert res.status_code == 409
    assert "变化" in res.json()["detail"]


# ============ created 文件回滚删除 ============


@pytest.mark.asyncio
async def test_patch_set_create_file_rollback(client, tmp_path):
    pid, root = await _project(client, tmp_path)
    psid = (
        await client.post(
            f"/projects/{pid}/patch-sets",
            json={
                "title": "新建 b.py",
                "files": [{"rel_path": "b.py", "new_content": "x = 1\n", "create": True}],
            },
        )
    ).json()["id"]
    assert not (root / "b.py").exists()

    res = await client.post(f"/patch-sets/{psid}/apply")
    assert res.status_code == 200, res.text
    assert (root / "b.py").read_text(encoding="utf-8") == "x = 1\n"

    res = await client.post(f"/patch-sets/{psid}/rollback")
    assert res.status_code == 200, res.text
    assert not (root / "b.py").exists()  # created 文件回滚为删除


# ============ 命令失败诊断（mock LLM）============


@pytest.mark.asyncio
async def test_diagnose_command_output(client, tmp_path, monkeypatch):
    pid, _ = await _project(client, tmp_path)
    _mock_chat(
        monkeypatch,
        {
            "summary": "导入错误",
            "error_files": [{"file": "a.py", "line": 3, "message": "ModuleNotFoundError"}],
            "suggestion": "安装缺失依赖",
        },
    )
    res = await client.post(
        f"/projects/{pid}/diagnose-command-output",
        json={
            "output": "ModuleNotFoundError: No module named 'x'",
            "returncode": 1,
            "args": ["pytest"],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["summary"] == "导入错误"
    assert body["error_files"][0]["file"] == "a.py"
    assert body["error_files"][0]["line"] == 3
    assert "依赖" in body["suggestion"]


# ============ 多文件 patch set ============


@pytest.mark.asyncio
async def test_patch_set_multi_file(client, tmp_path):
    pid, root = await _project(client, tmp_path)
    (root / "c.py").write_text("c = 1\n", encoding="utf-8")
    res = await client.post(
        f"/projects/{pid}/patch-sets",
        json={
            "title": "多文件",
            "files": [
                {"rel_path": "a.py", "new_content": "def v():\n    return 2\n"},
                {"rel_path": "c.py", "new_content": "c = 2\n"},
                {"rel_path": "d.py", "new_content": "d = 3\n", "create": True},
            ],
        },
    )
    assert res.status_code == 201, res.text
    psid = res.json()["id"]
    assert len(res.json()["files"]) == 3

    res = await client.post(f"/patch-sets/{psid}/apply")
    assert res.status_code == 200, res.text
    assert len(res.json()["written"]) == 3
    assert "return 2" in (root / "a.py").read_text(encoding="utf-8")
    assert (root / "d.py").exists()

    res = await client.post(f"/patch-sets/{psid}/rollback")
    assert res.status_code == 200
    assert not (root / "d.py").exists()  # created 文件回滚删除
    assert "return 1" in (root / "a.py").read_text(encoding="utf-8")
