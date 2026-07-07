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
    provider_type: str
    remote_provider_enabled: bool
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    claude_api_key: str
    claude_model: str


class SettingsUpdate(BaseModel):
    llm_model: str | None = None
    embed_model: str | None = None
    llm_temperature: float | None = None
    llm_context_length: int | None = None
    kb_enabled_by_default: bool | None = None
    provider_type: str | None = None
    remote_provider_enabled: bool | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    claude_api_key: str | None = None
    claude_model: str | None = None


def _to_out(d: dict[str, str]) -> SettingsOut:
    return SettingsOut(
        llm_model=d["llm_model"],
        embed_model=d["embed_model"],
        llm_temperature=float(d["llm_temperature"]),
        llm_context_length=int(d["llm_context_length"]),
        kb_enabled_by_default=d["kb_enabled_by_default"].lower() == "true",
        provider_type=d.get("provider_type", "ollama"),
        remote_provider_enabled=d.get("remote_provider_enabled", "false").lower()
        == "true",
        openai_api_key=d.get("openai_api_key", ""),
        openai_base_url=d.get("openai_base_url", ""),
        openai_model=d.get("openai_model", "gpt-4o-mini"),
        claude_api_key=d.get("claude_api_key", ""),
        claude_model=d.get("claude_model", "claude-3-5-sonnet-latest"),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_session)):
    return _to_out(await SettingsService(db).get_all())


@router.put("/settings", response_model=SettingsOut)
async def update_settings(
    updates: SettingsUpdate, db: AsyncSession = Depends(get_session)
):
    data = {}
    for k, v in updates.model_dump().items():
        if v is None:
            continue
        data[k] = str(v).lower() if isinstance(v, bool) else str(v)
    return _to_out(await SettingsService(db).update(data))
