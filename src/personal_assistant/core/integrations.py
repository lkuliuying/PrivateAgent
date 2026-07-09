"""本地集成样板（第八阶段 M8）：ICS 日历导入 -> 提醒 / 收件箱。

设计要点（对齐 docs/phase8-requirements.md §5.8/§9）：
- 本地只读：只读用户授权的本地文件，不联网、不外发。
- 隐私预览：preview() 解析并展示事件摘要（标题/时间/数量），确认后才创建对象。
- 来源追踪：创建的 reminder/inbox 带 source_type="integration:ics"、source_id=导入记录 id。
- 可撤销：reversal_info_json 记录本次创建的所有目标 id；revert() 按来源删除。
- trusted paths：导入前 assert_trusted 文件路径，未授权则拒绝。
- 可诊断：失败更新 source.last_status=failed 与 import.status=failed，前端/诊断可见。

ICS 解析为最小 VEVENT 解析器（stdlib），支持 RFC 5545 行展开、DATE/DateTime、Z 后缀；
RRULE/重复不在样板范围（仅取首次发生时间）。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import InboxItem, IntegrationImport, IntegrationSource, Reminder
from .permissions import assert_trusted
from .repo_inbox import InboxRepository
from .repo_integrations import IntegrationRepository
from .repo_reminders import ReminderRepository
from .repo_tools import TrustedPathRepository
from .timeutil import utcnow

ICS_SOURCE_TYPE = "integration:ics"

# 集成源 config_json 疑似凭据字段名模式（第八阶段审查：集成源不存凭据）。
_SECRET_OPT_RE = re.compile(r"(key|secret|password|token|cred|pwd)", re.IGNORECASE)


def _strip_secret_options(options: dict) -> dict:
    """剥离 options 中的疑似凭据字段，仅保留文件路径/选项。"""
    return {k: v for k, v in options.items() if not _SECRET_OPT_RE.search(str(k))}


# ============ ICS 解析（stdlib）============


def _unescape(s: str) -> str:
    """反转义 ICS 文本（\\\\ \\n \\, \\;）。"""
    return (
        s.replace("\\\\", "\x00")
        .replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\x00", "\\")
    )


def _parse_dt(value: str, params: dict[str, str]) -> datetime | None:
    v = value.strip()
    if params.get("VALUE") == "DATE" or (len(v) == 8 and v.isdigit()):
        try:
            return datetime.strptime(v, "%Y%m%d")
        except ValueError:
            return None
    if v.endswith("Z"):
        v = v[:-1]
    try:
        return datetime.strptime(v, "%Y%m%dT%H%M%S")
    except ValueError:
        return None


def parse_ics(content: str) -> list[dict[str, Any]]:
    """解析 ICS 文本，返回 VEVENT 列表。

    每个事件: {uid, summary, description, location, dtstart, dtend, all_day}。
    支持行展开（续行以空格/Tab 开头）；忽略 RRULE/重复（样板仅取首次发生）。
    """
    # 行展开：以空格/Tab 开头的行是上一行的续行
    unfolded: list[str] = []
    for raw in content.splitlines():
        if raw[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += raw[1:]
        else:
            unfolded.append(raw)
    events: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in unfolded:
        s = line.strip()
        if s == "BEGIN:VEVENT":
            cur = {}
        elif s == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            name_part, value = line.split(":", 1)
            parts = name_part.split(";")
            name = parts[0].upper()
            params = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
            if name == "UID":
                cur["uid"] = value.strip()
            elif name == "SUMMARY":
                cur["summary"] = _unescape(value)
            elif name == "DESCRIPTION":
                cur["description"] = _unescape(value)
            elif name == "LOCATION":
                cur["location"] = _unescape(value)
            elif name == "DTSTART":
                cur["dtstart"] = _parse_dt(value, params)
                cur["all_day"] = params.get("VALUE") == "DATE"
            elif name == "DTEND":
                cur["dtend"] = _parse_dt(value, params)
    return events


def _event_body(ev: dict[str, Any]) -> str:
    parts: list[str] = []
    if ev.get("location"):
        parts.append(f"地点：{ev['location']}")
    ds = ev.get("dtstart")
    if ds:
        parts.append(f"开始：{ds.strftime('%Y-%m-%d %H:%M')}")
    de = ev.get("dtend")
    if de:
        parts.append(f"结束：{de.strftime('%Y-%m-%d %H:%M')}")
    if ev.get("description"):
        parts.append(ev["description"])
    return "\n".join(parts)


def _read_ics(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _serialize_event(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "uid": ev.get("uid"),
        "summary": ev.get("summary"),
        "dtstart": ev["dtstart"].isoformat() if ev.get("dtstart") else None,
        "dtend": ev["dtend"].isoformat() if ev.get("dtend") else None,
        "all_day": ev.get("all_day", False),
    }


# ============ 服务 ============


class IntegrationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = IntegrationRepository(db)
        self.trusted = TrustedPathRepository(db)
        self.reminders = ReminderRepository(db)
        self.inbox = InboxRepository(db)

    async def list_sources(self) -> list[IntegrationSource]:
        return await self.repo.list_sources()

    async def create_source(
        self,
        *,
        kind: str,
        title: str,
        file_path: str,
        target: str = "reminder",
        options: dict | None = None,
    ) -> IntegrationSource:
        """创建集成源配置。config_json 只存文件路径与选项，严禁保存凭据。"""
        cfg: dict[str, Any] = {"file_path": file_path, "target": target}
        if options:
            cfg["options"] = _strip_secret_options(options)
        return await self.repo.create_source(
            kind=kind, title=title, config_json=cfg
        )

    async def preview(
        self, *, source_id: int | None = None, file_path: str | None = None
    ) -> dict[str, Any]:
        """隐私预览：解析 ICS 并展示事件摘要，不创建任何对象。"""
        path = file_path
        source = None
        if path is None:
            if source_id is None:
                raise ValueError("需提供 source_id 或 file_path")
            source = await self.repo.get_source(source_id)
            if source is None:
                raise KeyError("source")
            path = (source.config_json or {}).get("file_path")
            if not path:
                raise ValueError("集成源未配置 file_path")
        trusted = await self.trusted.all_paths()
        assert_trusted(path, trusted)
        events = parse_ics(_read_ics(path))
        return {
            "file_path": path,
            "event_count": len(events),
            "sample_titles": [e.get("summary") or "（无标题）" for e in events[:10]],
            "events": [_serialize_event(e) for e in events[:50]],
            "target": (source.config_json or {}).get("target", "reminder")
            if source
            else "reminder",
        }

    async def run_import(
        self, *, source_id: int, target: str | None = None
    ) -> IntegrationImport:
        """执行导入：解析 ICS，为每个事件创建 reminder/inbox，记录可撤销信息。"""
        source = await self.repo.get_source(source_id)
        if source is None:
            raise KeyError("source")
        tgt = target or (source.config_json or {}).get("target", "reminder")
        file_path = (source.config_json or {}).get("file_path")
        if not file_path:
            raise ValueError("集成源未配置 file_path")
        trusted = await self.trusted.all_paths()
        assert_trusted(file_path, trusted)
        events = parse_ics(_read_ics(file_path))

        imp = await self.repo.create_import(
            source_id=source_id,
            source_kind=source.kind,
            summary_json={
                "event_count": len(events),
                "sample_titles": [
                    e.get("summary") or "（无标题）" for e in events[:10]
                ],
                "file_path": file_path,
                "target": tgt,
            },
            target_type=tgt,
            status="imported",
        )
        reminder_ids: list[int] = []
        inbox_ids: list[int] = []
        try:
            for ev in events:
                title = ev.get("summary") or "（无标题）"
                ds = ev.get("dtstart")
                body = _event_body(ev)
                if tgt == "reminder" and ds is not None:
                    r = await self.reminders.create(
                        title=title,
                        due_at=ds,
                        body_md=body,
                        source_type=ICS_SOURCE_TYPE,
                        source_id=imp.id,
                    )
                    reminder_ids.append(r.id)
                else:
                    # 无时间的事件 / inbox 目标：落入收件箱（reminder 需 due_at）
                    it = await self.inbox.create(
                        title=title,
                        item_type="reminder",
                        body_md=body,
                        due_at=ds,
                        source_type=ICS_SOURCE_TYPE,
                        source_id=imp.id,
                    )
                    inbox_ids.append(it.id)
            await self.repo.update_import(
                imp.id,
                target_id=(
                    reminder_ids[0]
                    if reminder_ids
                    else (inbox_ids[0] if inbox_ids else None)
                ),
                reversal_info_json={
                    "reminder_ids": reminder_ids,
                    "inbox_ids": inbox_ids,
                },
            )
            await self.repo.update_source_status(
                source_id, last_status="succeeded", last_run_at=utcnow()
            )
        except Exception as e:  # noqa: BLE001
            # 清理本次已创建的 reminder/inbox，避免孤儿；记录 reversal_info 以便追溯
            for rid in reminder_ids:
                r = await self.reminders.get(rid)
                if r:
                    await self.db.delete(r)
            for iid in inbox_ids:
                it = await self.inbox.get(iid)
                if it:
                    await self.db.delete(it)
            await self.repo.update_import(
                imp.id,
                status="failed",
                error_message=str(e)[:1000],
                reversal_info_json={
                    "reminder_ids": reminder_ids,
                    "inbox_ids": inbox_ids,
                    "cleaned_up": True,
                },
            )
            await self.repo.update_source_status(
                source_id, last_status="failed", last_run_at=utcnow()
            )
            await self.db.commit()
            raise
        result = await self.repo.get_fresh(imp.id)
        assert result is not None
        return result

    async def revert(self, import_id: int) -> IntegrationImport:
        """撤销一次导入：按来源删除本次创建的 reminder/inbox，标记 reverted。"""
        imp = await self.repo.get_import(import_id)
        if imp is None:
            raise KeyError("import")
        if imp.status == "reverted":
            return imp
        rems = (
            (
                await self.db.execute(
                    select(Reminder).where(
                        Reminder.source_type == ICS_SOURCE_TYPE,
                        Reminder.source_id == import_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in rems:
            await self.db.delete(r)
        items = (
            (
                await self.db.execute(
                    select(InboxItem).where(
                        InboxItem.source_type == ICS_SOURCE_TYPE,
                        InboxItem.source_id == import_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for it in items:
            await self.db.delete(it)
        await self.repo.update_import(
            import_id, status="reverted", reverted_at=utcnow()
        )
        result = await self.repo.get_fresh(import_id)
        assert result is not None
        return result

    async def list_imports(self) -> list[IntegrationImport]:
        return await self.repo.list_imports()
