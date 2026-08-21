"""v0.7.0 E1：CodingPatchSet 仓储（状态机 CAS + 文件级状态）。

冻结依据：``docs/releases/v0.7.0/v0.7.0-e0-contracts-20260821.md`` §2.4。

仓储只做持久化与状态转换（CAS）；业务规则（预览计算、原子应用、
回滚）在 ``patch_set_service``。状态转换全部走 ``WHERE status = :expected``
条件更新，防止并发/重放把已终态（applied/rolled_back/partial_unknown）
的 PatchSet 重新激活（T8/T12）。
"""
from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CodingPatchSet, CodingPatchSetFile

PATCH_SET_TERMINAL_STATUSES = frozenset(
    {"applied", "failed", "rolled_back", "partial_unknown", "rejected"}
)


class PatchSetNotFound(LookupError):
    """PatchSet 不存在或不属于该 run。"""


class PatchSetStateConflict(RuntimeError):
    """状态 CAS 失败：当前状态不允许该转换（终态防重放）。"""


class CodingPatchSetRepository:
    """coding_patch_sets / coding_patch_set_files 的持久化与状态机。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ---- 查询 ----

    async def get_by_id(self, patch_set_id: str) -> CodingPatchSet | None:
        stmt = (
            select(CodingPatchSet)
            .where(CodingPatchSet.id == patch_set_id)
            .options(
                __import__("sqlalchemy.orm", fromlist=["selectinload"]).selectinload(
                    CodingPatchSet.files
                )
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_run(
        self, run_id: str, patch_set_id: str
    ) -> CodingPatchSet:
        """按 run 归属加载 PatchSet；不属于该 run 视为不存在（不泄露信息）。"""
        patch_set = await self.get_by_id(patch_set_id)
        if patch_set is None or patch_set.run_id != run_id:
            raise PatchSetNotFound(f"PatchSet 不存在: {patch_set_id}")
        return patch_set

    async def list_for_run(self, run_id: str) -> list[CodingPatchSet]:
        """E3：按 run 列出全部 PatchSet（完成条件/Artifact 投影用）。"""
        stmt = (
            select(CodingPatchSet)
            .where(CodingPatchSet.run_id == run_id)
            .order_by(CodingPatchSet.created_at, CodingPatchSet.id)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ---- 预览持久化 ----

    async def create_preview(
        self,
        *,
        run_id: str,
        project_id: int,
        workspace_id: int,
        base_head_sha: str | None,
        parameters_hash: str,
        file_count: int,
        additions: int,
        deletions: int,
        truncated: bool,
        diff_total_bytes: int,
        files: Sequence[dict[str, Any]],
    ) -> CodingPatchSet:
        """持久化 previewed 状态的 PatchSet 与 pending 文件行（单事务）。"""
        patch_set_id = str(uuid.uuid4())
        record = CodingPatchSet(
            id=patch_set_id,
            run_id=run_id,
            project_id=project_id,
            workspace_id=workspace_id,
            base_head_sha=base_head_sha,
            parameters_hash=parameters_hash,
            preview_version=1,
            status="previewed",
            file_count=file_count,
            additions=additions,
            deletions=deletions,
            truncated=truncated,
            diff_total_bytes=diff_total_bytes,
        )
        self.db.add(record)
        for ordinal, item in enumerate(files):
            self.db.add(
                CodingPatchSetFile(
                    id=str(uuid.uuid4()),
                    patch_set_id=patch_set_id,
                    ordinal=ordinal,
                    operation=item["operation"],
                    rel_path=item["rel_path"],
                    new_rel_path=item.get("new_rel_path"),
                    old_sha256=item.get("old_sha256"),
                    new_sha256=item.get("new_sha256"),
                    new_content=item.get("new_content"),
                    truncated=bool(item.get("truncated")),
                    diff_text=item["diff_text"],
                    status="pending",
                )
            )
        await self.db.commit()
        # 返回时预加载 files（selectinload），避免调用方在 async 上下文
        # 触发 lazy load（MissingGreenlet）
        loaded = await self.get_by_id(patch_set_id)
        if loaded is None:  # pragma: no cover - 刚提交过必然存在
            raise PatchSetNotFound(f"PatchSet 不存在: {patch_set_id}")
        return loaded

    # ---- 状态转换（CAS） ----

    async def transition_status(
        self,
        patch_set_id: str,
        expected: str,
        new_status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> CodingPatchSet:
        """CAS 状态转换：当前状态 != expected 时抛 PatchSetStateConflict。

        终态（applied/rolled_back/partial_unknown）不可再转换，
        由 expected 检查保证（重放/并发第二次 apply 走这里失败）。
        """
        values: dict[str, Any] = {"status": new_status}
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
        result = await self.db.execute(
            update(CodingPatchSet)
            .where(
                CodingPatchSet.id == patch_set_id,
                CodingPatchSet.status == expected,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise PatchSetStateConflict(
                f"PatchSet {patch_set_id} 状态不是 {expected}，拒绝转换到 {new_status}"
            )
        await self.db.commit()
        record = await self.get_by_id(patch_set_id)
        if record is None:  # pragma: no cover - 刚更新过必然存在
            raise PatchSetNotFound(f"PatchSet 不存在: {patch_set_id}")
        return record

    async def set_file_status(
        self, patch_set_id: str, ordinal: int, status: str, *, error_message: str | None = None
    ) -> None:
        """文件级状态更新（pending → applied/rolled_back/unknown）。"""
        values: dict[str, Any] = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        await self.db.execute(
            update(CodingPatchSetFile)
            .where(
                CodingPatchSetFile.patch_set_id == patch_set_id,
                CodingPatchSetFile.ordinal == ordinal,
            )
            .values(**values)
        )

    async def set_all_files_status(
        self, patch_set_id: str, status: str
    ) -> None:
        """把该 PatchSet 全部文件统一置为 status（回滚成功后用）。"""
        await self.db.execute(
            update(CodingPatchSetFile)
            .where(CodingPatchSetFile.patch_set_id == patch_set_id)
            .values(status=status)
        )

    async def mark_rejected_for_run(self, run_id: str) -> int:
        """审批拒绝/取消：把该 run 全部 previewed PatchSet 置为 rejected（CAS）。

        E0 契约 §2.4 状态机 ``previewed → rejected``（审批拒绝）；rejected 是
        人工处置终态，后续 apply 经服务层 ``status != previewed`` 检查一律
        拒绝（配合 dispatcher NON_IDEMPOTENT 防自动重放）。返回置位数。
        """
        result = await self.db.execute(
            update(CodingPatchSet)
            .where(
                CodingPatchSet.run_id == run_id,
                CodingPatchSet.status == "previewed",
            )
            .values(status="rejected")
        )
        if result.rowcount:
            await self.db.commit()
        return int(result.rowcount or 0)
