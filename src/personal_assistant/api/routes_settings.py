"""设置路由：GET / PUT /settings。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.settings import SettingsService

router = APIRouter(tags=["settings"])


class SettingsOut(BaseModel):
    llm_model: str
    embed_model: str
    llm_temperature: float
    llm_context_length: int
    kb_enabled_by_default: bool
    # Provider 接口位（第一阶段仅展示，不开放修改）
    openai_api_key: str
    openai_base_url: str
    claude_api_key: str


class SettingsUpdate(BaseModel):
    llm_model: str | None = None
    embed_model: str | None = None
    llm_temperature: float | None = None
    llm_context_length: int | None = None
    kb_enabled_by_default: bool | None = None


def _to_out(d: dict[str, str]) -> SettingsOut:
    return SettingsOut(
        llm_model=d["llm_model"],
        embed_model=d["embed_model"],
        llm_temperature=float(d["llm_temperature"]),
        llm_context_length=int(d["llm_context_length"]),
        kb_enabled_by_default=d["kb_enabled_by_default"].lower() == "true",
        openai_api_key=d.get("openai_api_key", ""),
        openai_base_url=d.get("openai_base_url", ""),
        claude_api_key=d.get("claude_api_key", ""),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_session)):
    return _to_out(await SettingsService(db).get_all())


@router.put("/settings", response_model=SettingsOut)
async def update_settings(
    updates: SettingsUpdate, db: AsyncSession = Depends(get_session)
):
    data = {k: str(v) for k, v in updates.model_dump().items() if v is not None}
    return _to_out(await SettingsService(db).update(data))
