"""第三阶段 M1 测试：项目工作区只读能力。

覆盖：
- 授权项目（建 project + 同步 trusted_paths + 去重）。
- 扫描忽略 .git/node_modules 等目录。
- 目录枚举 / 文件名搜索 / 内容 grep / 读取片段。
- 越界 rel_path 读取被拒（403）。
- 代码工具注册与风险等级。
- git status/diff 只读（本机有 git 时）。

照 test_phase2.py 模式：client fixture 走 ASGITransport + 真实 MySQL。
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess

import pytest

from personal_assistant.agents.contracts import ToolCall
from personal_assistant.agents.runtime import CancellationToken
from personal_assistant.core.code_tools import list_directory
from personal_assistant.core.permissions import PermissionError_
from personal_assistant.core.tool_adapter import build_read_only_tool_dispatcher
from personal_assistant.core.tools import default_registry

# ============ 工具注册 ============


def test_code_tools_registered():
    """M1 代码工具注册，风险等级正确。"""
    ld = default_registry.get("list_directory")
    s = default_registry.get("search_files")
    g = default_registry.get("grep_code")
    r = default_registry.get("read_code_file")
    gs = default_registry.get("get_git_status")
    gd = default_registry.get("get_git_diff")
    assert ld and ld.risk_level == "safe"
    assert s and s.risk_level == "safe"
    assert g and g.risk_level == "safe"
    assert r and r.risk_level == "confirm"
    assert gs and gs.risk_level == "safe"
    assert gd and gd.risk_level == "safe"
    names = {t["name"] for t in default_registry.for_planning()}
    assert {
        "list_directory",
        "search_files",
        "grep_code",
        "read_code_file",
        "get_git_status",
        "get_git_diff",
    }.issubset(names)


# ============ 项目授权 ============

@pytest.mark.asyncio
async def test_authorize_project_dedup(client, tmp_path):
    """POST /projects 创建项目并推断语言；重复授权同路径返回原项目。"""
    root = tmp_path / "proj1"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    res = await client.post(
        "/projects", json={"name": "proj1", "root_path": str(root)}
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "proj1"
    assert body["language"] == "Python"
    assert body["status"] == "active"
    pid = body["id"]

    # 重复授权同路径 → 返回原项目（去重）
    res2 = await client.post(
        "/projects", json={"name": "dup", "root_path": str(root)}
    )
    assert res2.status_code == 201
    assert res2.json()["id"] == pid

    # 列表包含该项目
    res3 = await client.get("/projects")
    assert any(p["id"] == pid for p in res3.json())


@pytest.mark.asyncio
async def test_authorize_invalid_path(client, tmp_path):
    """非绝对路径 → 422（字段校验）；不存在目录 → 400（业务校验）。"""
    res = await client.post(
        "/projects", json={"name": "x", "root_path": "relative/path"}
    )
    assert res.status_code == 422

    res2 = await client.post(
        "/projects", json={"name": "x", "root_path": str(tmp_path / "nope")}
    )
    assert res2.status_code == 400


# ============ 扫描 + 目录树 ============

async def _wait_for_scan(client, project_id: int, timeout_s: float = 10.0) -> dict:
    """轮询 /projects/{id}/stats 直到 total > 0 或超时。"""
    for _ in range(int(timeout_s * 5)):
        res = await client.get(f"/projects/{project_id}/stats")
        if res.status_code == 200 and res.json().get("total", 0) > 0:
            return res.json()
        await asyncio.sleep(0.2)
    return res.json()


@pytest.mark.asyncio
async def test_scan_ignores_dirs(client, tmp_path):
    """扫描忽略 .git/node_modules/__pycache__ 等；目录树不含忽略目录文件。"""
    root = tmp_path / "proj2"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def hello():\n    pass\n", encoding="utf-8")
    (root / "src" / "b.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "lib.js").write_text("module.exports=1;", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "a.cpython.pyc").write_bytes(b"\x00\x01")

    pid = (await client.post("/projects", json={"name": "p2", "root_path": str(root)})).json()["id"]
    await client.post(f"/projects/{pid}/scan")
    stats = await _wait_for_scan(client, pid)
    assert stats["total"] >= 2  # src/a.py + src/b.ts + pyproject 等非忽略文件

    tree = (await client.get(f"/projects/{pid}/tree")).json()
    flat = _flatten_tree(tree)
    assert any("src/a.py" in p for p in flat)
    assert not any(".git/config" in p for p in flat)
    assert not any("node_modules/lib.js" in p for p in flat)
    assert not any("__pycache__" in p for p in flat)


def _flatten_tree(node: dict) -> list[str]:
    """把目录树展平为文件路径列表。"""
    out = [f["path"] for f in node.get("files", [])]
    for d in node.get("dirs", []):
        out.append(d["path"])
        out.extend(_flatten_tree(d))
    return out


# ============ 搜索 / grep / 读取 ============

@pytest.mark.asyncio
async def test_list_directory_live_non_git_project(client, db, tmp_path):
    """无需 Git 或预扫描即可列根目录/子目录，并保持越界与输出上限。"""

    root = tmp_path / "plain-directory"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "README.md").write_text("# plain\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("ignored\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "pkg.js").write_text("ignored\n", encoding="utf-8")

    created = await client.post(
        "/projects", json={"name": "plain", "root_path": str(root)}
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    root_result = await list_directory(db, project_id)
    assert root_result["rel_path"] == "."
    assert [(item["name"], item["kind"]) for item in root_result["entries"]] == [
        ("src", "directory"),
        ("README.md", "file"),
    ]
    assert root_result["truncated"] is False

    src_result = await list_directory(db, project_id, "src")
    assert src_result["entries"] == [
        {
            "rel_path": "src/app.py",
            "name": "app.py",
            "kind": "file",
            "language": "Python",
            "size_bytes": (root / "src" / "app.py").stat().st_size,
        }
    ]

    bounded = await list_directory(db, project_id, limit=1)
    assert bounded["count"] == 1
    assert bounded["truncated"] is True

    dispatcher = build_read_only_tool_dispatcher(db)
    dispatched = await dispatcher.execute(
        ToolCall(
            id="list-root",
            name="list_directory",
            arguments={"project_id": project_id},
        ),
        cancellation=CancellationToken(),
    )
    assert dispatched.success is True
    assert dispatched.output == root_result

    missing_query = await dispatcher.execute(
        ToolCall(
            id="search-without-query",
            name="search_files",
            arguments={"project_id": project_id},
        ),
        cancellation=CancellationToken(),
    )
    assert missing_query.success is True
    assert missing_query.output == {
        "mode": "directory",
        "rel_path": ".",
        "results": [
            {
                "rel_path": item["rel_path"],
                "name": item["name"],
                "kind": item["kind"],
                "language": item["language"],
                "size_bytes": item["size_bytes"],
            }
            for item in root_result["entries"]
        ],
        "count": root_result["count"],
        "truncated": False,
    }

    blank_query = await dispatcher.execute(
        ToolCall(
            id="search-with-blank-query",
            name="search_files",
            arguments={"project_id": project_id, "query": "   "},
        ),
        cancellation=CancellationToken(),
    )
    assert blank_query.success is True
    assert blank_query.output == missing_query.output

    invalid = await dispatcher.execute(
        ToolCall(
            id="list-empty-path",
            name="list_directory",
            arguments={"project_id": project_id, "rel_path": ""},
        ),
        cancellation=CancellationToken(),
    )
    assert invalid.success is False
    assert invalid.error_code == "input_schema_invalid"

    with pytest.raises(PermissionError_):
        await list_directory(db, project_id, "../outside")
    with pytest.raises(FileNotFoundError, match="目录不存在"):
        await list_directory(db, project_id, "missing")
    with pytest.raises(NotADirectoryError, match="不是目录"):
        await list_directory(db, project_id, "README.md")


async def _make_scanned_project(client, tmp_path) -> int:
    root = tmp_path / "proj3"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(
        "def hello_world():\n    return 'greet'\n\nx = hello_world()\n", encoding="utf-8"
    )
    (root / "src" / "util.ts").write_text(
        "export function greet() { return 1; }\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# proj3\n", encoding="utf-8")
    pid = (await client.post("/projects", json={"name": "p3", "root_path": str(root)})).json()["id"]
    await client.post(f"/projects/{pid}/scan")
    await _wait_for_scan(client, pid)
    return pid


@pytest.mark.asyncio
async def test_search_files_by_name(client, db, tmp_path):
    pid = await _make_scanned_project(client, tmp_path)
    res = await client.get(f"/projects/{pid}/search", params={"query": "app", "kind": "name"})
    assert res.status_code == 200
    paths = [r["rel_path"] for r in res.json()["results"]]
    assert any("app.py" in p for p in paths)

    dispatcher = build_read_only_tool_dispatcher(db)
    tool_result = await dispatcher.execute(
        ToolCall(
            id="search-app",
            name="search_files",
            arguments={"project_id": pid, "query": " app "},
        ),
        cancellation=CancellationToken(),
    )
    assert tool_result.success is True
    assert tool_result.output["mode"] == "search"
    assert tool_result.output["count"] >= 1
    assert all(item["kind"] == "file" for item in tool_result.output["results"])
    assert any(
        item["rel_path"].endswith("src/app.py")
        for item in tool_result.output["results"]
    )


@pytest.mark.asyncio
async def test_grep_code_content(client, tmp_path):
    pid = await _make_scanned_project(client, tmp_path)
    res = await client.get(
        f"/projects/{pid}/search", params={"query": "hello_world", "kind": "content"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["count"] >= 1
    hit = body["results"][0]
    assert "app.py" in hit["rel_path"]
    assert hit["line"] == 1
    assert "hello_world" in hit["context"]


@pytest.mark.asyncio
async def test_read_code_file(client, tmp_path):
    pid = await _make_scanned_project(client, tmp_path)
    res = await client.get(
        f"/projects/{pid}/read", params={"rel_path": "src/app.py"}
    )
    assert res.status_code == 200
    body = res.json()
    assert "hello_world" in body["content"]
    assert body["language"] == "Python"
    assert body["line_count"] >= 3


@pytest.mark.asyncio
async def test_read_code_file_escape_rejected(client, tmp_path):
    """rel_path 含 .. 越界 → 403。"""
    pid = await _make_scanned_project(client, tmp_path)
    res = await client.get(
        f"/projects/{pid}/read", params={"rel_path": "../../etc/passwd"}
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_read_code_file_absolute_rejected(client, tmp_path):
    """绝对路径 rel_path → 403。"""
    pid = await _make_scanned_project(client, tmp_path)
    res = await client.get(
        f"/projects/{pid}/read", params={"rel_path": "/etc/passwd"}
    )
    assert res.status_code == 403


# ============ git status / diff（本机有 git 时）============

has_git = shutil.which("git") is not None


@pytest.mark.asyncio
@pytest.mark.skipif(not has_git, reason="本机无 git")
async def test_git_status_and_diff(client, tmp_path):
    """初始化 git 仓库后，git status 返回分支与改动；git diff 返回 diff 文本。只读。"""
    root = tmp_path / "gitproj"
    root.mkdir()
    env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}
    subprocess.check_call(
        ["git", "init", "-q"], cwd=str(root), env=env
    )
    subprocess.check_call(
        ["git", "config", "user.email", "t@t"], cwd=str(root), env=env
    )
    subprocess.check_call(
        ["git", "config", "user.name", "t"], cwd=str(root), env=env
    )
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "a.txt"], cwd=str(root), env=env)
    subprocess.check_call(
        ["git", "commit", "-q", "-m", "init"], cwd=str(root), env=env
    )
    # 制造未暂存改动
    (root / "a.txt").write_text("hello world\n", encoding="utf-8")
    (root / "b.txt").write_text("new\n", encoding="utf-8")

    pid = (await client.post("/projects", json={"name": "gp", "root_path": str(root)})).json()["id"]

    st = await client.get(f"/projects/{pid}/git/status")
    assert st.status_code == 200, st.text
    sbody = st.json()
    assert sbody["branch"]
    assert not sbody["clean"]
    changed_paths = {c["path"] for c in sbody["changed"]}
    assert "a.txt" in changed_paths or "b.txt" in changed_paths

    diff = await client.get(f"/projects/{pid}/git/diff")
    assert diff.status_code == 200
    assert "diff" in diff.json()
    # diff 不应为空（有改动）
    assert diff.json()["diff"]
