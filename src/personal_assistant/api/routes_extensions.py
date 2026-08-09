"""扩展注册表路由（第八阶段 M7）。

- GET    /extensions          列出所有注册项（合并持久化 enabled 状态），可按 kind 过滤
- PATCH  /extensions/{id}     启用/禁用可配置扩展（不绕过审批状态机）

对齐 docs/archive/phases/phase8-requirements.md §7（GET /extensions、PATCH /extensions/{id}）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.extensions import extension_registry

router = APIRouter(tags=["extensions"])


class ExtensionPatch(BaseModel):
    enabled: bool


@router.get("/extensions")
async def list_extensions(
    kind: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """列出所有扩展注册项（含 command / capture_source / provider /
    diagnostic_check / maintenance_check / notification_target）。"""
    return await extension_registry.list_with_state(db, kind=kind)


@router.patch("/extensions/{ext_id}")
async def patch_extension(
    ext_id: str, body: ExtensionPatch, db: AsyncSession = Depends(get_session)
) -> dict:
    """启用/禁用可配置扩展。不可配置扩展返回 403。"""
    try:
        return await extension_registry.set_enabled(db, ext_id, body.enabled)
    except KeyError:
        raise HTTPException(404, f"扩展不存在: {ext_id}")
    except PermissionError as e:
        raise HTTPException(403, str(e))
