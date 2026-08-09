"""第八阶段 M3 测试：升级 smoke 工具与数据保留校验。

覆盖（对齐 docs/archive/phases/phase8-plan.md §M3 / docs/archive/phases/phase8-requirements.md §5.3）：
- verify_data_preservation：保留 / 丢失判定。
- build_runbook：含执行步骤 + 负面场景 + 回滚。
- snapshot_counts：覆盖全部 PRESERVATION_TABLES。
- record_run + GET /testing/upgrade-smoke-runs：记录与列表。
- GET /testing/runs：测试运行摘要路由。
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from personal_assistant.config import settings as cfg
from personal_assistant.core.models import UpgradeSmokeRun

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import upgrade_smoke as us  # noqa: E402


@asynccontextmanager
async def _fresh():
    engine = create_async_engine(cfg.db_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as s:
            yield s
    finally:
        await engine.dispose()


def test_verify_data_preservation_ok():
    before = {"sessions": 5, "documents": 3, "memory_items": 2}
    after = {"sessions": 5, "documents": 3, "memory_items": 2}
    res = us.verify_data_preservation(before, after)
    assert res["preserved"] is True
    assert not any(d["lost"] for d in res["deltas"])


def test_verify_data_preservation_allows_growth():
    before = {"sessions": 5}
    after = {"sessions": 7}
    res = us.verify_data_preservation(before, after)
    assert res["preserved"] is True  # 新增允许


def test_verify_data_preservation_detects_loss():
    before = {"sessions": 5, "documents": 3, "memory_items": 2}
    after = {"sessions": 5, "documents": 2, "memory_items": 2}
    res = us.verify_data_preservation(before, after)
    assert res["preserved"] is False
    lost_tables = [d["table"] for d in res["deltas"] if d["lost"]]
    assert "documents" in lost_tables
    assert "sessions" not in lost_tables


def test_build_runbook_has_sections():
    rb = us.build_runbook()
    assert "升级 smoke runbook" in rb
    assert "负面场景" in rb
    assert "回滚" in rb
    assert "待真实环境执行" in rb
    assert "--snapshot" in rb and "--verify" in rb


@pytest.mark.asyncio
async def test_snapshot_counts_covers_all_tables():
    counts = await us.snapshot_counts()
    for table in us.PRESERVATION_TABLES:
        assert table in counts
        assert isinstance(counts[table], int)


@pytest.mark.asyncio
async def test_record_run_and_route(client):
    rid = await us.record_run("0.1.1", "0.1.2", "blocked", None, None, "本机无法真实升级")
    assert rid > 0
    try:
        resp = await client.get("/testing/upgrade-smoke-runs")
        assert resp.status_code == 200
        assert any(r["id"] == rid for r in resp.json())
        # 记录的字段
        item = next(r for r in resp.json() if r["id"] == rid)
        assert item["from_version"] == "0.1.1"
        assert item["to_version"] == "0.1.2"
        assert item["result"] == "blocked"
    finally:
        async with _fresh() as s:
            row = await s.get(UpgradeSmokeRun, rid)
            if row:
                await s.delete(row)
                await s.commit()


@pytest.mark.asyncio
async def test_list_test_runs_route(client):
    resp = await client.get("/testing/runs")
    assert resp.status_code == 200
    # 按 kind 过滤
    resp = await client.get("/testing/runs?kind=release_check")
    assert resp.status_code == 200
    assert all(r["kind"] == "release_check" for r in resp.json())
