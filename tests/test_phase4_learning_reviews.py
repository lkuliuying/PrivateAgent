"""第四阶段 M2 测试：学习系统 2.0（间隔重复复习）。

覆盖：卡片评分更新 due_at / 今日复习只显到期 / again lapse / 三档间隔递增 /
dashboard 统计 / 薄弱点 / 错题本 / 周报（mock LLM）/ 学习复习候选记忆（mock LLM）。

卡片/练习/答题直接经 db 建立以避免 LLM 不确定性；周报与候选记忆 monkeypatch
OllamaProvider.chat 返回固定 JSON。按 id 断言（不依赖列表为空），autouse fixture
清理本测试创建的主题（CASCADE 清卡片/复习/练习/答题）与候选记忆。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from personal_assistant.core.provider import OllamaProvider
from personal_assistant.core.timeutil import utcnow

# ============ helpers ============


def _mock_chat(monkeypatch, payload) -> None:
    """让 OllamaProvider.chat 返回 payload（str 或可序列化对象）。"""
    text = (
        json.dumps(payload, ensure_ascii=False)
        if isinstance(payload, (list, dict))
        else payload
    )

    async def fake_chat(self, messages):
        return text

    monkeypatch.setattr(OllamaProvider, "chat", fake_chat)


async def _make_topic(client, topic_ids: list[int], title: str = "操作系统") -> int:
    res = await client.post(
        "/learning/topics", json={"title": title, "goal": "掌握基础"}
    )
    assert res.status_code == 201, res.text
    tid = res.json()["id"]
    topic_ids.append(tid)
    return tid


async def _make_card(
    db,
    topic_id: int,
    *,
    front: str = "什么是进程？",
    back: str = "进程是程序运行的实例",
    due_at: datetime | None = None,
    interval_days: int = 0,
    ease_factor: float = 2.5,
    review_count: int = 0,
    lapse_count: int = 0,
) -> int:
    from personal_assistant.core.models import LearningCard

    c = LearningCard(
        topic_id=topic_id,
        front=front,
        back=back,
        due_at=due_at,
        interval_days=interval_days,
        ease_factor=ease_factor,
        review_count=review_count,
        lapse_count=lapse_count,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c.id


@pytest.fixture(autouse=True)
async def _cleanup(client, db):
    """清理本测试创建的主题（CASCADE 清子表）与候选记忆。"""
    topic_ids: list[int] = []
    mem_ids: list[int] = []
    yield topic_ids, mem_ids
    from personal_assistant.core.models import LearningTopic

    for mid in mem_ids:
        try:
            await client.delete(f"/memories/{mid}")
        except Exception:  # noqa: BLE001
            pass
    for tid in topic_ids:
        t = await db.get(LearningTopic, tid)
        if t:
            await db.delete(t)
            await db.commit()


# ============ 评分更新 due_at ============


@pytest.mark.asyncio
async def test_card_review_updates_due(client, db, _cleanup):
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    cid = await _make_card(db, tid, due_at=utcnow())  # 到期

    res = await client.post(f"/learning/cards/{cid}/review", json={"rating": "good"})
    assert res.status_code == 200, res.text
    body = res.json()
    card, review = body["card"], body["review"]

    assert card["review_count"] == 1
    assert card["interval_days"] == 1
    # due_at 推后到未来（≥ 23 小时后）
    due = datetime.fromisoformat(card["due_at"])
    assert due > utcnow() + timedelta(hours=23)
    assert review["rating"] == "good"
    assert review["card_id"] == cid
    assert review["next_due_at"] == card["due_at"]
    assert review["previous_due_at"] is not None  # 之前 due_at=now
    # previous_due_at 必须是旧值（≈now），早于新 due_at；防止 commit 过期后误读新值
    prev = datetime.fromisoformat(review["previous_due_at"])
    assert prev < due


# ============ 今日复习只显到期 ============


@pytest.mark.asyncio
async def test_today_only_due(client, db, _cleanup):
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    due_id = await _make_card(db, tid, front="到期卡", due_at=utcnow())
    notdue_id = await _make_card(
        db, tid, front="未到期卡", due_at=utcnow() + timedelta(days=5)
    )

    res = await client.get("/learning/reviews/today", params={"topic_id": tid})
    assert res.status_code == 200
    ids = [c["id"] for c in res.json()]
    assert due_id in ids
    assert notdue_id not in ids

    # 评分到期卡为 good → 推后，不再到期
    await client.post(f"/learning/cards/{due_id}/review", json={"rating": "good"})
    res = await client.get("/learning/reviews/today", params={"topic_id": tid})
    ids = [c["id"] for c in res.json()]
    assert due_id not in ids


# ============ again lapse ============


@pytest.mark.asyncio
async def test_again_lapse(client, db, _cleanup):
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    cid = await _make_card(db, tid, due_at=utcnow())

    # 先 good 一次让 review_count=1
    await client.post(f"/learning/cards/{cid}/review", json={"rating": "good"})
    # 再 again → lapse
    res = await client.post(f"/learning/cards/{cid}/review", json={"rating": "again"})
    assert res.status_code == 200
    card = res.json()["card"]
    assert card["review_count"] == 0
    assert card["lapse_count"] == 1
    # again 短间隔：10 分钟内
    due = datetime.fromisoformat(card["due_at"])
    assert due <= utcnow() + timedelta(minutes=11)


# ============ 三档间隔递增 ============


@pytest.mark.asyncio
async def test_intervals_hard_good_easy(client, db, _cleanup):
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    # 三张卡同处 interval=4, review=3 状态，分别评 hard/good/easy
    cid_h = await _make_card(
        db, tid, front="h", interval_days=4, review_count=3, due_at=utcnow()
    )
    cid_g = await _make_card(
        db, tid, front="g", interval_days=4, review_count=3, due_at=utcnow()
    )
    cid_e = await _make_card(
        db, tid, front="e", interval_days=4, review_count=3, due_at=utcnow()
    )

    rh = (
        await client.post(f"/learning/cards/{cid_h}/review", json={"rating": "hard"})
    ).json()["card"]
    rg = (
        await client.post(f"/learning/cards/{cid_g}/review", json={"rating": "good"})
    ).json()["card"]
    re = (
        await client.post(f"/learning/cards/{cid_e}/review", json={"rating": "easy"})
    ).json()["card"]

    # hard=round(4*1.2)=5, good=round(4*2.5)=10, easy=round(4*2.6*1.3)=14
    assert rh["interval_days"] == 5
    assert rg["interval_days"] == 10
    assert re["interval_days"] == 14
    assert rh["interval_days"] < rg["interval_days"] < re["interval_days"]
    # ease：hard 罚、good 不变、easy 奖
    assert rh["ease_factor"] < rg["ease_factor"] < re["ease_factor"]


# ============ dashboard 统计 ============


@pytest.mark.asyncio
async def test_dashboard_stats(client, db, _cleanup):
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    await _make_card(db, tid, front="到期", due_at=utcnow())
    await _make_card(
        db, tid, front="未到期", due_at=utcnow() + timedelta(days=3)
    )
    from personal_assistant.core.models import LearningNode

    db.add(LearningNode(topic_id=tid, title="进程", order_index=0, mastery_level="mastered"))
    db.add(LearningNode(topic_id=tid, title="线程", order_index=1, mastery_level="vague"))
    await db.commit()

    res = await client.get(f"/learning/topics/{tid}/dashboard")
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["total_cards"] == 2
    assert d["due_today"] == 1
    assert d["total_nodes"] == 2
    assert d["mastered_nodes"] == 1
    assert d["weak_nodes"] == 1


# ============ 薄弱点 ============


@pytest.mark.asyncio
async def test_weak_points(client, db, _cleanup):
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    from personal_assistant.core.models import LearningCard, LearningNode

    db.add(
        LearningNode(
            topic_id=tid, title="薄弱节点", order_index=0, mastery_level="unknown"
        )
    )
    c = LearningCard(
        topic_id=tid, front="遗忘卡", back="答", lapse_count=2, due_at=utcnow()
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)

    res = await client.get(f"/learning/topics/{tid}/weak-points")
    assert res.status_code == 200, res.text
    items = res.json()
    kinds = [it["kind"] for it in items]
    assert "node" in kinds
    assert "card" in kinds
    card_item = next(it for it in items if it["kind"] == "card")
    assert card_item["id"] == c.id
    assert card_item["lapse_count"] == 2


# ============ 错题本 ============


@pytest.mark.asyncio
async def test_wrong_answers(client, db, _cleanup):
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    from personal_assistant.core.models import LearningQuiz, LearningQuizAttempt

    q = LearningQuiz(
        topic_id=tid,
        question="进程和线程的区别？",
        answer="进程是资源单位，线程是执行单位",
        explanation="资源 vs 执行",
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    db.add(LearningQuizAttempt(quiz_id=q.id, user_answer="不知道", result="wrong"))
    db.add(LearningQuizAttempt(quiz_id=q.id, user_answer="差不多", result="partial"))
    await db.commit()

    res = await client.get(f"/learning/topics/{tid}/wrong-answers")
    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) == 2
    assert all(it["result"] in ("wrong", "partial") for it in items)
    assert items[0]["question"] == "进程和线程的区别？"
    assert items[0]["reference_answer"] == "进程是资源单位，线程是执行单位"


# ============ 周报（mock LLM）============


@pytest.mark.asyncio
async def test_weekly_report(client, db, monkeypatch, _cleanup):
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    from personal_assistant.core.models import LearningCard, LearningReview

    c = LearningCard(topic_id=tid, front="卡", back="答", due_at=utcnow())
    db.add(c)
    await db.commit()
    await db.refresh(c)
    db.add(
        LearningReview(
            card_id=c.id,
            topic_id=tid,
            rating="good",
            previous_due_at=None,
            next_due_at=utcnow() + timedelta(days=1),
        )
    )
    await db.commit()

    _mock_chat(monkeypatch, "## 本周学习报告\n\n进展不错，继续保持。")
    res = await client.post(f"/learning/topics/{tid}/weekly-report")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "本周" in body["report_md"]
    assert body["stats"]["reviews_7d"] == 1
    assert body["stats"]["rating_counts"]["good"] == 1


# ============ 学习复习候选记忆（mock LLM，补 M1 defer）============


@pytest.mark.asyncio
async def test_candidates_from_learning_review(client, db, monkeypatch, _cleanup):
    topic_ids, mem_ids = _cleanup
    tid = await _make_topic(client, topic_ids)
    from personal_assistant.core.models import LearningCard, LearningReview

    c = LearningCard(topic_id=tid, front="进程", back="实例", due_at=utcnow())
    db.add(c)
    await db.commit()
    await db.refresh(c)
    db.add(
        LearningReview(
            card_id=c.id,
            topic_id=tid,
            rating="again",
            previous_due_at=None,
            next_due_at=utcnow(),
        )
    )
    await db.commit()

    _mock_chat(
        monkeypatch,
        [
            {
                "kind": "learning",
                "title": "OS 进程概念薄弱",
                "content_md": "用户在进程概念上反复遗忘，需要重点复习。",
                "summary": "进程薄弱",
            }
        ],
    )
    res = await client.post(
        "/memories/candidates",
        json={"source_type": "learning_review", "source_id": tid},
    )
    assert res.status_code == 201, res.text
    items = res.json()
    assert len(items) == 1
    it = items[0]
    assert it["status"] == "draft"
    assert it["source_type"] == "learning_review"
    assert it["source_id"] == tid
    assert it["topic_id"] == tid
    assert it["kind"] == "learning"
    mem_ids.extend(it["id"] for it in items)


# ============ 调度回归：good 不缩短 / hard 不停滞（review workflow 发现）============


@pytest.mark.asyncio
async def test_good_no_regression_after_easy(client, db, _cleanup):
    """首评 easy(interval=4) 后二评 good 不应缩短间隔，且 hard<good<easy。"""
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    cid = await _make_card(db, tid, due_at=utcnow())
    r1 = (
        await client.post(f"/learning/cards/{cid}/review", json={"rating": "easy"})
    ).json()["card"]
    assert r1["interval_days"] == 4
    assert r1["review_count"] == 1

    r2 = (
        await client.post(f"/learning/cards/{cid}/review", json={"rating": "good"})
    ).json()["card"]
    assert r2["interval_days"] >= 4  # good 不应缩短 easy 后的间隔

    # 同状态(interval=4,count=1,ease=2.6)二评三档递增
    cid_h = await _make_card(
        db, tid, front="h", interval_days=4, review_count=1, ease_factor=2.6, due_at=utcnow()
    )
    cid_g = await _make_card(
        db, tid, front="g", interval_days=4, review_count=1, ease_factor=2.6, due_at=utcnow()
    )
    cid_e = await _make_card(
        db, tid, front="e", interval_days=4, review_count=1, ease_factor=2.6, due_at=utcnow()
    )
    rh = (
        await client.post(f"/learning/cards/{cid_h}/review", json={"rating": "hard"})
    ).json()["card"]
    rg = (
        await client.post(f"/learning/cards/{cid_g}/review", json={"rating": "good"})
    ).json()["card"]
    re = (
        await client.post(f"/learning/cards/{cid_e}/review", json={"rating": "easy"})
    ).json()["card"]
    assert rh["interval_days"] < rg["interval_days"] < re["interval_days"]


@pytest.mark.asyncio
async def test_hard_grows_from_low_interval(client, db, _cleanup):
    """interval=1 时反复 hard 不应永久停滞在 1。"""
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    cid = await _make_card(
        db, tid, interval_days=1, review_count=1, ease_factor=2.5, due_at=utcnow()
    )
    r = (
        await client.post(f"/learning/cards/{cid}/review", json={"rating": "hard"})
    ).json()["card"]
    assert r["interval_days"] >= 2  # 略延长，不再塌缩为 1


# ============ UTC 7 天窗口（review workflow 发现）============


@pytest.mark.asyncio
async def test_utc_7day_window(client, db, _cleanup):
    """6 天 20 小时前的复习记录应计入 reviews_7d（naive UTC 基准）。"""
    topic_ids, _ = _cleanup
    tid = await _make_topic(client, topic_ids)
    from personal_assistant.core.models import LearningCard, LearningReview

    c = LearningCard(topic_id=tid, front="卡", back="答", due_at=utcnow())
    db.add(c)
    await db.commit()
    await db.refresh(c)
    backdated = utcnow() - timedelta(days=6, hours=20)
    db.add(
        LearningReview(
            card_id=c.id,
            topic_id=tid,
            rating="good",
            previous_due_at=None,
            next_due_at=utcnow() + timedelta(days=1),
            created_at=backdated,
        )
    )
    await db.commit()

    res = await client.get(f"/learning/topics/{tid}/dashboard")
    assert res.status_code == 200
    assert res.json()["reviews_7d"] == 1


# ============ 候选记忆：不存在的会话 404（review workflow 发现）============


@pytest.mark.asyncio
async def test_candidates_from_chat_missing_session_404(client, _cleanup):
    res = await client.post(
        "/memories/candidates",
        json={"source_type": "chat_session", "source_id": 999999},
    )
    assert res.status_code == 404
