"""间隔重复调度算法（SM-2 变体，第四阶段 M2）。

采用 4 按钮评分 × SM-2 ease-factor 公式 × Anki 风格间隔倍率的混合方案：

- 评分语义对齐需求「again 短间隔 / hard 略延长 / good 正常延长 / easy 明显延长」。
- ease_factor 用经典 SM-2 公式更新（quality 0-5），下限 1.3。
- 间隔倍率取 Anki 直觉：hard=×1.2、good=×EF、easy=×EF×1.3，使三档递增明显。
- good 二次复习取 3 天（原版 SM-2 为 6 天），对每日密集学习更温和。

纯函数 + 可注入 now，便于单元测试与确定性调度。无 DB 依赖。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .timeutil import utcnow

# 评分 → SM-2 quality(0-5) 映射。
RATING_QUALITY: dict[str, int] = {
    "again": 0,  # 忘记：lapse，重学
    "hard": 3,   # 模糊：略延长
    "good": 4,   # 记得：正常延长
    "easy": 5,   # 熟练：明显延长
}

# 重学步长（again 后多久再次出现）。
RELEARN_MINUTES = 10
# ease_factor 下限（SM-2 规定）。
MIN_EASE = 1.3
# easy 间隔奖励倍率。
EASY_BONUS = 1.3
# hard 间隔倍率。
HARD_FACTOR = 1.2


@dataclass
class CardState:
    """调度输入：卡片当前调度状态。"""

    interval_days: int
    ease_factor: float
    review_count: int
    lapse_count: int


@dataclass
class ScheduleResult:
    """调度输出：评分后卡片的新调度状态 + 下次到期时间。"""

    interval_days: int
    ease_factor: float
    review_count: int
    lapse_count: int
    due_at: datetime


def _update_ease(ease: float, quality: int) -> float:
    """SM-2 ease_factor 更新公式：EF' = EF + 0.1 - (5-q)(0.08 + (5-q)0.02)，下限 1.3。"""
    delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    return max(MIN_EASE, round(ease + delta, 4))


def schedule(
    state: CardState,
    rating: str,
    now: datetime | None = None,
) -> ScheduleResult:
    """根据评分计算卡片下次调度。

    again：lapse——review_count 归零、lapse_count+1、间隔 0、due=now+10min（重学步长）。
    hard/good/easy：review_count+1，按倍率延长间隔，due=now+interval 天。
    """
    if rating not in RATING_QUALITY:
        raise ValueError(f"未知评分: {rating}（应为 again/hard/good/easy）")
    quality = RATING_QUALITY[rating]
    now = now or utcnow()
    new_ease = _update_ease(state.ease_factor, quality)

    if rating == "again":
        # 重学：短间隔，计数归零，记录一次 lapse。
        return ScheduleResult(
            interval_days=0,
            ease_factor=new_ease,
            review_count=0,
            lapse_count=state.lapse_count + 1,
            due_at=now + timedelta(minutes=RELEARN_MINUTES),
        )

    new_review_count = state.review_count + 1
    prev = state.interval_days

    if rating == "hard":
        # 略延长：保证至少 prev+1，避免低间隔时 round(×1.2) 塌缩为零增长（永久停滞）。
        interval = 1 if new_review_count == 1 else max(prev + 1, round(prev * HARD_FACTOR))
    elif rating == "good":
        if new_review_count == 1:
            interval = 1
        elif new_review_count == 2:
            # 二次取 3 天为基线，但不低于 prev×EF，避免首评 easy 后 good 反而缩短间隔。
            interval = max(3, round(prev * state.ease_factor))
        else:
            interval = max(1, round(prev * state.ease_factor))
    else:  # easy
        interval = 4 if new_review_count == 1 else max(1, round(prev * new_ease * EASY_BONUS))

    return ScheduleResult(
        interval_days=interval,
        ease_factor=new_ease,
        review_count=new_review_count,
        lapse_count=state.lapse_count,
        due_at=now + timedelta(days=interval),
    )


def due_label(due_at: datetime | None, now: datetime | None = None) -> str:
    """人类可读的到期标签（供前端/周报），非调度核心。"""
    if due_at is None:
        return "未排期"
    now = now or utcnow()
    if due_at <= now:
        return "今日到期"
    secs = (due_at - now).total_seconds()
    if secs < 86400:
        hours = max(1, round(secs / 3600))
        return f"{hours} 小时后"
    days = math.ceil(secs / 86400)
    return f"{days} 天后"
