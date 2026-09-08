"""S3 按行续读、真实读取版本和路径边界。"""
import os
import subprocess

import pytest

from private_agent_local import files
from private_agent_local.repository import Repository
from private_agent_local.store import Store


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    store = Store(tmp_path / "state.sqlite3")
    run = {"id": "run", "status": "completed", "workspace_id": 1, "permission_mode": "workspace"}
    store.save_run(run)
    yield Repository(store), run, root
    store.db.close()


def test_large_file_tail_empty_and_version_continuation(repository):
    repo, run, root = repository
    (root / "中文 空格.py").write_bytes(b"\xef\xbb\xbf" + "".join(f"line {n}\r\n" for n in range(1, 2501)).encode())
    first = repo.read(run, root, "中文 空格.py", 1, 10)
    assert first["next_line"] == 11 and first["total_lines"] == 2500
    assert first["line_numbers"] == list(range(1, 11)) and first["content"].startswith("line 1\r\n")
    tail = repo.read(run, root, "中文 空格.py", 2499, 10, first["sha256"])
    assert tail["content"] == "line 2499\r\nline 2500\r\n" and tail["next_line"] is None
    (root / "中文 空格.py").write_text("user changed", encoding="utf-8")
    with pytest.raises(ValueError, match="版本已变化"):
        repo.read(run, root, "中文 空格.py", 11, 10, first["sha256"])
    (root / "empty").write_bytes(b"")
    empty = repo.read(run, root, "empty")
    assert empty["total_lines"] == 0 and empty["end_line"] == 0 and empty["content"] == ""
    with pytest.raises(ValueError):
        repo.read(run, root, "empty", 2)
    with pytest.raises(ValueError):
        repo.snapshot("other-run", first["snapshot_id"])


@pytest.mark.parametrize("relative", ["../outside", "x/../a", "CON.txt", "a.", "a ", "a//b", "a:ads", ".env", ".codex/x"])
def test_unsafe_paths_never_read(repository, relative):
    repo, run, root = repository
    with pytest.raises((ValueError, OSError)):
        repo.read(run, root, relative)


def test_hardlink_binary_invalid_encoding_and_case_alias(repository):
    repo, run, root = repository
    (root / "A.txt").write_text("original")
    with pytest.raises(ValueError):
        repo.read(run, root, "a.txt")
    os.link(root / "A.txt", root / "hard.txt")
    with pytest.raises(ValueError, match="硬链接"):
        repo.read(run, root, "hard.txt")
    for name, value in [("binary", b"a\x00b"), ("encoding", b"\xff\xfe")]:
        (root / name).write_bytes(value)
        with pytest.raises((ValueError, UnicodeError)):
            repo.read(run, root, name)


def test_actual_symlink_rejected(repository, tmp_path):
    repo, run, root = repository
    outside = tmp_path / "outside.txt"
    outside.write_text("external")
    try:
        (root / "link").symlink_to(outside)
    except OSError:
        pytest.skip("当前 Windows 环境未授予创建真实符号链接权限")
    with pytest.raises(ValueError):
        repo.read(run, root, "link")
    assert files.digest(outside.read_bytes()) == files.digest(b"external")


def test_single_long_line_can_be_continued_without_losing_tail(repository):
    repo, run, root = repository
    content = "a" * (files.MAX_OUTPUT + 100) + "尾部"
    (root / "long").write_text(content, encoding="utf-8")
    first = repo.read(run, root, "long")
    assert first["next_line"] == 1 and first["next_column"] == files.MAX_OUTPUT + 1
    tail = repo.read(run, root, "long", first["next_line"], 1, first["sha256"], first["next_column"])
    assert first["content"] + tail["content"] == content and tail["next_line"] is None


@pytest.mark.skipif(os.name != "nt", reason="真实目录联接只适用 Windows")
def test_actual_windows_junction_is_rejected(repository, tmp_path):
    repo, run, root = repository
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x").write_text("outside")
    junction = root / "junction"
    script = "New-Item -ItemType Junction -Path '" + str(junction).replace("'", "''") + "' -Target '" + str(outside).replace("'", "''") + "' -ErrorAction Stop | Out-Null"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, timeout=10)
    if result.returncode:
        pytest.skip("当前环境无法创建真实 Windows 目录联接")
    assert junction.is_junction()
    with pytest.raises(ValueError):
        repo.read(run, root, "junction/x")
    assert (outside / "x").read_text() == "outside"
