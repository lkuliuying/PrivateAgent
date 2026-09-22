"""S3 搜索分页、忽略规则、降级与游标失效。"""
import asyncio
import threading

import pytest

from private_agent_local import repository


@pytest.mark.asyncio
async def test_search_all_pages_cursor_replay_and_changes(tmp_path):
    for number in range(7):
        (tmp_path / f"file{number}.py").write_text(f"needle {number}\nNEEDLE second\n")
    first = await repository.search(tmp_path, "needle", content=True, limit=3)
    assert first["total"] == 14
    second = await repository.search(tmp_path, "needle", content=True, limit=3, cursor=first["next_cursor"])
    assert second == await repository.search(tmp_path, "needle", content=True, limit=3, cursor=first["next_cursor"])
    results, cursor = first["results"], first["next_cursor"]
    while cursor:
        result = await repository.search(tmp_path, "needle", content=True, limit=3, cursor=cursor)
        results += result["results"]
        cursor = result["next_cursor"]
    assert len({(row["rel_path"], row["line"]) for row in results}) == 14
    with pytest.raises(ValueError, match="游标"):
        await repository.search(tmp_path, "other", content=True, cursor=first["next_cursor"])
    (tmp_path / "file6.py").write_text("needle changed\n")
    with pytest.raises(ValueError, match="游标"):
        await repository.search(tmp_path, "needle", content=True, cursor=first["next_cursor"])


@pytest.mark.asyncio
async def test_ignores_secrets_glob_regex_and_missing_rg(tmp_path, monkeypatch):
    (tmp_path / ".gitignore").write_text("ignored/\n*.log\n!keep.log\n")
    (tmp_path / "ignored").mkdir()
    for name in ("a.py", "a.log", "keep.log", ".env", "ignored/a.py"):
        (tmp_path / name).write_text("match 123\n")
    result = await repository.search(tmp_path, "match", content=True)
    assert {item["rel_path"] for item in result["results"]} == {"a.py", "keep.log"}
    result = await repository.search(tmp_path, "match", content=True, glob="**/*.py")
    assert [item["rel_path"] for item in result["results"]] == ["a.py"]
    if repository.shutil.which("rg"):
        result = await repository.search(tmp_path, r"match \d+", content=True, regex=True)
        assert result["count"] == 2
        with pytest.raises(ValueError):
            await repository.search(tmp_path, "[", content=True, regex=True)
    monkeypatch.setattr(repository.shutil, "which", lambda _: None)
    result = await repository.search(tmp_path, "match", content=True)
    assert result["backend"] == "python_literal" and result["count"] == 2
    with pytest.raises(ValueError, match="需要本机 rg"):
        await repository.search(tmp_path, "match", regex=True)


def test_directory_pagination_is_stable_and_invalidated(tmp_path):
    for name in ("b", "a", "C"):
        (tmp_path / name).write_text(name)
    first = repository.directory(tmp_path, limit=1)
    assert first["entries"][0]["name"] == "a"
    second = repository.directory(tmp_path, cursor=first["next_cursor"], limit=1)
    assert second["entries"][0]["name"] == "b"
    (tmp_path / "new").write_text("new")
    with pytest.raises(ValueError, match="游标"):
        repository.directory(tmp_path, cursor=first["next_cursor"])


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", ["null", "0", "not-a-cursor"])
async def test_invalid_cursor_is_rejected_with_restart_guidance(tmp_path, cursor):
    (tmp_path / "app.py").write_text("needle\n")
    with pytest.raises(ValueError, match="cursor=null"):
        repository.directory(tmp_path, cursor=cursor)
    with pytest.raises(ValueError, match="cursor=null"):
        await repository.search(tmp_path, "app", cursor=cursor)
    assert repository.directory(tmp_path, cursor=None)["entries"][0]["name"] == "app.py"
    assert (await repository.search(tmp_path, "app", cursor=None))["results"][0]["rel_path"] == "app.py"


@pytest.mark.asyncio
async def test_cursor_cannot_cross_tools_and_changed_queries_restart_explicitly(tmp_path):
    for name in ("app.py", "other.py"):
        (tmp_path / name).write_text("needle\n")
    first = repository.directory(tmp_path, limit=1)
    with pytest.raises(ValueError, match="cursor=null"):
        await repository.search(tmp_path, ".py", cursor=first["next_cursor"])
    search = await repository.search(tmp_path, ".py", limit=1)
    with pytest.raises(ValueError, match="cursor=null"):
        await repository.search(tmp_path, "app", cursor=search["next_cursor"])
    assert (await repository.search(tmp_path, "app", cursor=None))["count"] == 1


@pytest.mark.asyncio
async def test_cancel_search_stops_scanning_at_next_file(tmp_path, monkeypatch):
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("needle\n")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    reads = []
    original_read, original_scan = repository.files.safe_bytes, repository.scan

    def read(root, relative):
        reads.append(relative)
        entered.set()
        if not release.wait(5):
            raise TimeoutError("测试读取未释放")
        return original_read(root, relative)

    def scan(*args, **kwargs):
        try:
            return original_scan(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(repository.shutil, "which", lambda _: None)
    monkeypatch.setattr(repository.files, "safe_bytes", read)
    monkeypatch.setattr(repository, "scan", scan)
    task = asyncio.create_task(repository.search(tmp_path, "needle", content=True))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert await asyncio.to_thread(finished.wait, 5)
    assert reads == ["a.py"]
