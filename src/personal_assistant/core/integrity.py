"""数据完整性体检与修复计划服务（第七阶段 M7）。

检查跨模块软引用悬空、Chroma/MySQL 切片一致性、可归档旧对象、备份 manifest。
发现项持久化到 data_integrity_findings（支持 ignored/resolved 避免重复打扰）。
修复计划只预览，apply 不默认删除用户数据（phase7 §7 风险控制）。

检查项（对齐 docs/archive/phases/phase7-requirements.md §5.7）：
- goal_links 悬空（goal_id 或 target_id 失效）
- briefings.sources_json 悬空
- inbox source/target 悬空
- document_collection_items.doc_id 悬空
- Chroma chunk 与 MySQL doc_chunks 不一致
- 长期已完成对象可归档
- 备份 manifest 缺 schema 版本
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .backup import BackupService
from .extensions import ExtensionDescriptor, ExtensionKind, extension_registry
from .models import (
    AgentTask,
    Briefing,
    ChatSession,
    DataIntegrityFinding,
    DocChunk,
    Document,
    DocumentCollection,
    GoalLink,
    InboxItem,
    LearningTopic,
    MemoryItem,
    Message,
    PersonalGoal,
    Project,
    Reminder,
)
from .store_chroma import chroma_store
from .timeutil import utcnow

# 软引用 target_type -> ORM 模型（用于悬空校验）
TARGET_TABLES: dict[str, type] = {
    "learning_topic": LearningTopic,
    "learning_note": LearningTopic,  # 笔记悬空归结到主题
    "project": Project,
    "agent_task": AgentTask,
    "collection": DocumentCollection,
    "document_collection": DocumentCollection,
    "document": Document,
    "chat_session": ChatSession,
    "chat_message": Message,
    "memory": MemoryItem,
    "reminder": Reminder,
    "inbox": InboxItem,
    "goal": PersonalGoal,
    "activity": type("A", (), {"__table__": None}),  # 占位，活动不校验
}

ARCHIVE_DAYS = 90


class IntegrityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def check(self) -> list[DataIntegrityFinding]:
        """执行全部检查，持久化新发现项（跳过已 ignored/resolved 的同位问题）。"""
        raw: list[dict] = []
        # 第八阶段 M7：遍历已注册且启用的 maintenance_check，调用其 runner。
        # 新增体检检查只需注册描述符，即自动进入 check() 流程，无需改本方法。
        for desc in extension_registry.list(kind=ExtensionKind.MAINTENANCE_CHECK):
            if desc.runner is None:
                continue
            if not await extension_registry.is_enabled(self.db, desc.id):
                continue
            try:
                raw.extend(await desc.runner(self))
            except Exception:  # noqa: BLE001
                # 单个检查失败不阻断其余检查
                continue

        # 批量去重：一次查询取回相关 check_name 的既有 finding，避免逐条 _find_existing（N+1）。
        existing_map = await self._find_existing_bulk(raw)
        out: list[DataIntegrityFinding] = []
        new_findings: list[DataIntegrityFinding] = []
        for f in raw:
            key = (f["check_name"], f.get("ref_type"), f.get("ref_id"))
            existing = existing_map.get(key)
            if existing is not None:
                if existing.status == "open":
                    existing.detail_json = f.get("detail_json")
                    existing.severity = f.get("severity", existing.severity)
                    existing.suggested_action = f.get("suggested_action")
                    out.append(existing)
                # ignored/resolved：不重复打扰
                continue
            finding = DataIntegrityFinding(
                check_name=f["check_name"],
                severity=f.get("severity", "warning"),
                ref_type=f.get("ref_type"),
                ref_id=f.get("ref_id"),
                detail_json=f.get("detail_json"),
                suggested_action=f.get("suggested_action"),
                status="open",
            )
            self.db.add(finding)
            new_findings.append(finding)
            out.append(finding)
            # 防止同一 run 内重复 (check_name, ref_type, ref_id) 再插入（原逐条提交能查到，
            # 批量预取查不到本次新增）：把新键登记进 existing_map，后续命中走 open 更新分支。
            existing_map[key] = finding
        # 单次提交（替代逐条 commit），减少 N 次往返。
        await self.db.commit()
        for finding in new_findings:
            await self.db.refresh(finding)
        return out

    async def _find_existing_bulk(self, raw: list[dict]) -> dict:
        """一次查询取回 raw 涉及的 check_name 的既有 finding，按 (check_name, ref_type, ref_id) 索引。"""
        check_names = list({f["check_name"] for f in raw})
        if not check_names:
            return {}
        stmt = select(DataIntegrityFinding).where(DataIntegrityFinding.check_name.in_(check_names))
        rows = (await self.db.execute(stmt)).scalars().all()
        return {(r.check_name, r.ref_type, r.ref_id): r for r in rows}

    async def _existing_ids(self, model: type, ids: list[int]) -> set[int]:
        """批量查询 model 中存在的 id 集合（替代逐个 _exists，避免 N+1）。"""
        if not ids:
            return set()
        rows = (await self.db.execute(select(model.id).where(model.id.in_(ids)))).scalars().all()
        return set(rows)

    async def list_findings(self, *, status: str | None = None) -> list[DataIntegrityFinding]:
        stmt = select(DataIntegrityFinding)
        if status:
            stmt = stmt.where(DataIntegrityFinding.status == status)
        stmt = stmt.order_by(DataIntegrityFinding.created_at.desc())
        return list((await self.db.execute(stmt)).scalars().all())

    async def set_status(self, finding_id: int, status: str) -> DataIntegrityFinding | None:
        f = await self.db.get(DataIntegrityFinding, finding_id)
        if f is None:
            return None
        f.status = status
        await self.db.commit()
        await self.db.refresh(f)
        return f

    async def repair_plan(self) -> list[dict]:
        """生成修复计划（预览，不执行）。每项含 finding + suggested_action + 影响范围。"""
        findings = await self.list_findings(status="open")
        plan: list[dict] = []
        for f in findings:
            plan.append(
                {
                    "finding_id": f.id,
                    "check_name": f.check_name,
                    "severity": f.severity,
                    "ref_type": f.ref_type,
                    "ref_id": f.ref_id,
                    "suggested_action": f.suggested_action,
                    "detail": f.detail_json,
                    "impact": _impact_of(f),
                    "destructive": f.suggested_action in {"delete_orphan", "archive"},
                }
            )
        return plan

    async def apply(self, finding_id: int) -> dict:
        """执行单条修复计划。destructive 操作仅标记/重建，不删用户业务数据。"""
        f = await self.db.get(DataIntegrityFinding, finding_id)
        if f is None:
            return {"ok": False, "error": "finding not found"}
        action = f.suggested_action or "ignore"
        result: dict = {"finding_id": finding_id, "action": action, "ok": True}

        if action == "ignore":
            f.status = "ignored"
        elif action == "reindex":
            # Chroma 缺向量：标记需重建（不在此直接跑长任务）
            result["note"] = "已标记，请在知识库页对相关文档重建索引"
            f.status = "ignored"
        elif action == "delete_orphan":
            # Chroma 孤立向量：按 chunk_id 删除该切片的向量（仅向量，不删 MySQL）。
            # ref_id 是 chunk_id（doc_chunks.id），不是 doc_id，必须用 delete_by_chunk_id
            # （按 chroma id 删）；用 delete_by_doc 会按 doc_id 元数据删，误删别的文档。
            # 失败时保持 open，不标记 resolved，避免永久抑制复检（check 去重会跳过 resolved）。
            if f.ref_id is None:
                result["ok"] = False
                result["error"] = "delete_orphan 缺 ref_id"
            else:
                try:
                    await chroma_store.delete_by_chunk_id(f.ref_id)
                    result["deleted_orphan_chunk_id"] = f.ref_id
                    f.status = "resolved"
                except Exception as e:  # noqa: BLE001
                    result["ok"] = False
                    result["error"] = str(e)
        elif action == "archive":
            # 可归档旧对象：标记为 resolved，实际归档由用户在对应页面执行
            result["note"] = "请在对应页面手动归档"
            f.status = "ignored"
        elif action == "relink":
            f.status = "ignored"
            result["note"] = "请手动重新关联"
        else:
            f.status = "ignored"

        await self.db.commit()
        return result

    # ---- 检查项 ----

    async def _check_goal_links(self) -> list[dict]:
        from collections import defaultdict

        links = list((await self.db.execute(select(GoalLink))).scalars().all())
        if not links:
            return []
        existing_goals = await self._existing_ids(
            PersonalGoal, list({ln.goal_id for ln in links})
        )
        by_type: dict[str, list] = defaultdict(list)
        for ln in links:
            by_type[ln.target_type].append(ln)
        existing_targets: dict[str, set[int]] = {}
        for ttype, lns in by_type.items():
            model = TARGET_TABLES.get(ttype)
            if model is None:
                continue
            existing_targets[ttype] = await self._existing_ids(
                model, list({ln.target_id for ln in lns})
            )
        out: list[dict] = []
        for ln in links:
            if ln.goal_id not in existing_goals:
                out.append(self._f("goal_links_dangling", "goal_link", ln.id,
                                   {"goal_id": ln.goal_id, "reason": "goal_id 不存在"}, "relink", "error"))
                continue
            if ln.target_type in existing_targets and ln.target_id not in existing_targets[ln.target_type]:
                out.append(self._f("goal_links_dangling", "goal_link", ln.id,
                                   {"goal_id": ln.goal_id, "target_type": ln.target_type,
                                    "target_id": ln.target_id, "reason": "target 不存在"},
                                   "relink", "warning"))
        return out

    async def _check_briefing_sources(self) -> list[dict]:
        from collections import defaultdict

        briefings = list((await self.db.execute(select(Briefing))).scalars().all())
        if not briefings:
            return []
        by_type: dict[str, set[int]] = defaultdict(set)
        refs: list[tuple] = []
        for b in briefings:
            srcs = b.sources_json or []
            if not isinstance(srcs, list):
                continue
            for s in srcs:
                if not isinstance(s, dict):
                    continue
                t = s.get("type") or s.get("source_type")
                sid = s.get("id") or s.get("source_id")
                if t is None or sid is None or TARGET_TABLES.get(t) is None:
                    continue
                try:
                    sid_i = int(sid)
                except (TypeError, ValueError):
                    continue
                by_type[t].add(sid_i)
                refs.append((b, t, sid_i))
        existing: dict[str, set[int]] = {}
        for t, ids in by_type.items():
            existing[t] = await self._existing_ids(TARGET_TABLES[t], list(ids))
        out: list[dict] = []
        for b, t, sid in refs:
            if sid not in existing.get(t, set()):
                out.append(self._f("briefing_sources_dangling", "briefing", b.id,
                                   {"source_type": t, "source_id": sid, "briefing_id": b.id},
                                   "ignore", "info"))
        return out

    async def _check_inbox_refs(self) -> list[dict]:
        from collections import defaultdict

        items = list((await self.db.execute(select(InboxItem))).scalars().all())
        if not items:
            return []
        by_type: dict[str, set[int]] = defaultdict(set)
        refs: list[tuple] = []
        for i in items:
            for kind, t, sid in (("source", i.source_type, i.source_id),
                                 ("target", i.target_type, i.target_id)):
                if not t or sid is None or TARGET_TABLES.get(t) is None:
                    continue
                by_type[t].add(sid)
                refs.append((i, kind, t, sid))
        existing: dict[str, set[int]] = {}
        for t, ids in by_type.items():
            existing[t] = await self._existing_ids(TARGET_TABLES[t], list(ids))
        out: list[dict] = []
        for i, kind, t, sid in refs:
            if sid not in existing.get(t, set()):
                out.append(self._f("inbox_ref_dangling", "inbox", i.id,
                                   {"kind": kind, "ref_type": t, "ref_id": sid},
                                   "ignore", "info"))
        return out

    async def _check_collection_items(self) -> list[dict]:
        from .models import DocumentCollectionItem

        items = list(
            (await self.db.execute(select(DocumentCollectionItem))).scalars().all()
        )
        if not items:
            return []
        existing_docs = await self._existing_ids(
            Document, list({it.doc_id for it in items})
        )
        out: list[dict] = []
        for it in items:
            if it.doc_id not in existing_docs:
                out.append(self._f("collection_items_dangling", "collection_item", it.id,
                                   {"collection_id": it.collection_id, "doc_id": it.doc_id},
                                   "ignore", "warning"))
        return out

    async def _check_chroma_mysql(self) -> list[dict]:
        """Chroma chunk 与 MySQL doc_chunks 一致性。"""
        out: list[dict] = []
        try:
            mysql_rows = list(
                (await self.db.execute(select(DocChunk.id))).scalars().all()
            )
            mysql_ids = set(mysql_rows)
            chroma_ids = set(await chroma_store.list_ids())
        except Exception:  # noqa: BLE001
            return out
        mysql_only = list(mysql_ids - chroma_ids)
        chroma_only = list(chroma_ids - mysql_ids)
        for cid in mysql_only[:50]:
            out.append(self._f("chroma_mysql_mismatch", "chunk", cid,
                               {"side": "mysql_only", "reason": "MySQL 有切片但 Chroma 缺向量"},
                               "reindex", "warning"))
        for cid in chroma_only[:50]:
            out.append(self._f("chroma_mysql_mismatch", "chunk", cid,
                               {"side": "chroma_only", "reason": "Chroma 有孤立向量（MySQL 已删）"},
                               "delete_orphan", "warning"))
        return out

    async def _check_archivable(self) -> list[dict]:
        """长期已完成对象可归档（> ARCHIVE_DAYS 天）。"""
        cutoff = utcnow() - timedelta(days=ARCHIVE_DAYS)
        out: list[dict] = []
        # 已完成收件箱
        done_inbox = list(
            (await self.db.execute(
                select(InboxItem).where(InboxItem.status.in_(["done", "ignored"]))
            )).scalars().all()
        )
        for i in done_inbox:
            if i.handled_at and i.handled_at < cutoff:
                out.append(self._f("archivable_old", "inbox", i.id,
                                   {"status": i.status, "handled_at": i.handled_at.isoformat()},
                                   "archive", "info"))
        # 已完成提醒
        done_rem = list(
            (await self.db.execute(
                select(Reminder).where(Reminder.status == "done")
            )).scalars().all()
        )
        for r in done_rem:
            if r.updated_at and r.updated_at < cutoff:
                out.append(self._f("archivable_old", "reminder", r.id,
                                   {"status": "done", "updated_at": r.updated_at.isoformat()},
                                   "archive", "info"))
        return out

    async def _check_backup_manifest(self) -> list[dict]:
        """备份 manifest 校验：缺 app_version/schema_head/checksum 或 checksum 不匹配。"""
        out: list[dict] = []
        try:
            backup = await BackupService(self.db).list()
            items = backup.get("items") or []
            if not items:
                return out
            latest = items[0]
            validation = await BackupService(self.db).validate_manifest(latest["path"])
            if not validation["valid"]:
                out.append(
                    self._f(
                        "backup_manifest",
                        "backup",
                        None,
                        {
                            "path": latest["path"],
                            "issues": validation["issues"],
                            "reason": "备份 manifest 校验失败",
                        },
                        "ignore",
                        "warning",
                    )
                )
        except Exception:  # noqa: BLE001
            pass
        return out

    # ---- 辅助 ----

    async def _exists(self, model: type, obj_id: int | None) -> bool:
        if obj_id is None:
            return False
        return (await self.db.get(model, obj_id)) is not None

    async def _find_existing(
        self, check_name: str, ref_type: str | None, ref_id: int | None
    ) -> DataIntegrityFinding | None:
        stmt = select(DataIntegrityFinding).where(
            DataIntegrityFinding.check_name == check_name,
            DataIntegrityFinding.ref_type.is_(ref_type) if ref_type is None
            else DataIntegrityFinding.ref_type == ref_type,
        )
        if ref_id is None:
            stmt = stmt.where(DataIntegrityFinding.ref_id.is_(None))
        else:
            stmt = stmt.where(DataIntegrityFinding.ref_id == ref_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _f(
        check_name: str,
        ref_type: str | None,
        ref_id: int | None,
        detail: dict,
        action: str,
        severity: str,
    ) -> dict:
        return {
            "check_name": check_name,
            "ref_type": ref_type,
            "ref_id": ref_id,
            "detail_json": detail,
            "suggested_action": action,
            "severity": severity,
        }


def _impact_of(f: DataIntegrityFinding) -> str:
    """修复动作的影响范围描述。"""
    action = f.suggested_action or "ignore"
    detail = f.detail_json or {}
    if action == "delete_orphan":
        return f"删除 Chroma 中孤立向量（chunk #{f.ref_id}），不影响 MySQL 数据"
    if action == "reindex":
        return f"对 chunk #{f.ref_id} 重建向量，需重新嵌入"
    if action == "archive":
        return f"归档 {f.ref_type} #{f.ref_id}（已完成超过 {ARCHIVE_DAYS} 天）"
    if action == "relink":
        return f"重新关联 {f.ref_type} #{f.ref_id}（{detail.get('reason', '引用悬空')}）"
    return f"标记 {f.ref_type} #{f.ref_id} 为忽略"


def _register_integrity_checks() -> None:
    """注册内置 maintenance_check（附带 runner），幂等。

    内置体检检查 configurable=False（始终运行，避免漏检）；新增检查可设
    configurable=True 由用户启用/禁用。runner 签名：Callable[[IntegrityService], Awaitable[list[dict]]]。
    """
    checks = [
        ("goal_links_dangling", "目标关联悬空检查", "relink",
         lambda svc: svc._check_goal_links()),
        ("briefing_sources_dangling", "简报来源悬空检查", "ignore",
         lambda svc: svc._check_briefing_sources()),
        ("inbox_ref_dangling", "收件箱引用悬空检查", "ignore",
         lambda svc: svc._check_inbox_refs()),
        ("collection_items_dangling", "集合成员悬空检查", "ignore",
         lambda svc: svc._check_collection_items()),
        ("chroma_mysql_mismatch", "Chroma/MySQL 切片一致性检查", "reindex",
         lambda svc: svc._check_chroma_mysql()),
        ("archivable_old", "可归档旧对象检查", "archive",
         lambda svc: svc._check_archivable()),
        ("backup_manifest", "备份 manifest 完整性检查", "ignore",
         lambda svc: svc._check_backup_manifest()),
    ]
    for cid, title, action, runner in checks:
        if extension_registry.get(cid) is None:
            extension_registry.register(
                ExtensionDescriptor(
                    id=cid,
                    title=title,
                    kind=ExtensionKind.MAINTENANCE_CHECK,
                    description=title,
                    risk_level="safe",
                    permissions=["read:integrity"],
                    output_summary=f"产生 {action} 类发现项",
                    runner=runner,
                    configurable=False,
                )
            )


_register_integrity_checks()
