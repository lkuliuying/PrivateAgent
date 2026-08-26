"""v1.0 CT-3（专项计划 §8.2/§8.3）：模型工具能力探测的生产接入。

组成：
- :func:`build_gateway_for_profile`：按 profile 构建模型网关（与
  run 路由同源；本地强制 loopback、远程需全局启用——零猜测）；
- :class:`ModelProbeSnapshotRepository`：探测快照持久化（durable 事实）；
- :func:`run_probe_for_profile`：执行固定用例集并落快照（成功/失败都落库）；
- :func:`auto_probe_profile`：模型配置保存后的自动探测入口（尽力而为，
  不阻断配置保存；``PA_AGENT_V2_MODEL_PROBE_ENABLED`` 关闭时跳过）；
- :func:`profile_tool_protocol_valid`：工具面门禁事实——最新快照
  status=ok 且 function_calling 能力成立才允许副作用工具面；无有效快照
  失败关闭（§8.2 末条：只暴露最小 JSON Function 工具集）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from personal_assistant.core.models import (
    ModelProfile,
    ModelToolProfileSnapshotRecord,
)

from ..agent_v2.application.model_probe import (
    ModelToolProfileSnapshot,
    run_probe,
)

#: 自动探测整体超时（本地 14B 6 用例约 30~120s；超时按失败快照落库）。
AUTO_PROBE_TIMEOUT_S = 240.0

PROBE_STATUS_OK = "ok"
PROBE_STATUS_FAILED = "failed"


def build_gateway_for_profile(
    profile: ModelProfile,
    provider_settings: Mapping[str, str],
    *,
    default_temperature: float,
    default_context_length: int,
    ollama_base_url: str,
):
    """按 profile 事实构建模型网关（provider/model 缺失即失败关闭）。

    与 api/routes_agent_runs 的 run 路由同源：本地 profile 强制 loopback
    （不得把本地上下文送往远程）；远程 provider 需全局启用。
    """
    from urllib.parse import urlsplit

    from .model_profiles import ModelProfileUnsupported

    routed_model_name = (profile.model_name or "").strip()
    if not routed_model_name:
        raise ModelProfileUnsupported(
            f"模型 profile {profile.id} 缺少具体模型路由字段（model_name）"
        )
    remote_enabled = (
        provider_settings.get("remote_provider_enabled", "false").lower() == "true"
    )
    temperature = float(
        provider_settings.get("llm_temperature", default_temperature)
    )
    provider = (profile.provider or "").strip().lower()
    if profile.is_local or provider == "ollama":
        from ..llm import ModelGateway, OllamaChatAdapter

        parsed_host = (urlsplit(ollama_base_url).hostname or "").lower()
        if parsed_host not in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
            raise ModelProfileUnsupported(
                f"模型 profile {profile.id} 是本地 profile，但 ollama_base_url "
                f"指向非本地主机（{parsed_host or '(空)'}），拒绝路由"
            )
        return ModelGateway(
            OllamaChatAdapter(
                base_url=ollama_base_url,
                model=routed_model_name,
                temperature=temperature,
                context_length=int(
                    profile.context_tokens
                    or provider_settings.get(
                        "llm_context_length", default_context_length
                    )
                ),
                trust_env=False,
                require_loopback=True,
            )
        )
    if provider == "openai":
        if not remote_enabled:
            raise ModelProfileUnsupported(
                f"模型 profile {profile.id} 是远程 Provider（openai），"
                "但全局远程 Provider 未启用"
            )
        from ..llm import ModelGateway, OpenAIChatAdapter

        return ModelGateway(
            OpenAIChatAdapter(
                base_url=provider_settings.get("openai_base_url")
                or "https://api.openai.com/v1",
                api_key=provider_settings.get("openai_api_key") or "",
                model=routed_model_name,
                temperature=temperature,
            )
        )
    if provider == "claude":
        if not remote_enabled:
            raise ModelProfileUnsupported(
                f"模型 profile {profile.id} 是远程 Provider（claude），"
                "但全局远程 Provider 未启用"
            )
        from ..llm import ClaudeMessagesAdapter, ModelGateway

        return ModelGateway(
            ClaudeMessagesAdapter(
                api_key=provider_settings.get("claude_api_key") or "",
                model=routed_model_name,
                temperature=temperature,
            )
        )
    raise ModelProfileUnsupported(
        f"模型 profile {profile.id} 的 provider 不受支持: {provider}"
    )


class ModelProbeSnapshotRepository:
    """探测快照读写（durable 事实；每次探测一行，门禁取最新一条）。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def save(
        self,
        profile_id: str,
        snapshot: ModelToolProfileSnapshot,
        *,
        status: str = PROBE_STATUS_OK,
        error_code: str | None = None,
    ) -> ModelToolProfileSnapshotRecord:
        record = ModelToolProfileSnapshotRecord(
            profile_id=profile_id,
            provider=snapshot.provider,
            model_name=snapshot.model_name,
            model_digest=snapshot.model_digest,
            status=status,
            error_code=error_code,
            sample_count=snapshot.sample_count,
            pass_count=snapshot.pass_count,
            results_json=dict(snapshot.results),
            requirements_json=snapshot.requirements.model_dump(mode="json"),
            probed_at=snapshot.probed_at.replace(tzinfo=None),
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def save_failed(
        self,
        profile_id: str,
        *,
        provider: str,
        model_name: str,
        error_code: str,
    ) -> ModelToolProfileSnapshotRecord:
        from datetime import datetime

        record = ModelToolProfileSnapshotRecord(
            profile_id=profile_id,
            provider=provider,
            model_name=model_name,
            model_digest="",
            status=PROBE_STATUS_FAILED,
            error_code=error_code[:64],
            sample_count=0,
            pass_count=0,
            results_json=None,
            requirements_json=None,
            probed_at=datetime.utcnow(),
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def latest(self, profile_id: str) -> ModelToolProfileSnapshotRecord | None:
        statement = (
            select(ModelToolProfileSnapshotRecord)
            .where(ModelToolProfileSnapshotRecord.profile_id == profile_id)
            .order_by(ModelToolProfileSnapshotRecord.created_at.desc())
            .limit(1)
        )
        return (await self.db.execute(statement)).scalars().first()


async def profile_tool_protocol_valid(
    db: AsyncSession, profile: ModelProfile
) -> bool:
    """工具面门禁事实：最新快照 ok 且 function_calling 能力成立。

    与 profile 当前 model_name 的 digest 不一致（换模型后未重新探测）
    同样视为无效——未知能力失败关闭（AD-T04）。
    """
    if not profile.native_tool_calls:
        return False
    record = await ModelProbeSnapshotRepository(db).latest(profile.id)
    if record is None or record.status != PROBE_STATUS_OK:
        return False
    requirements = record.requirements_json or {}
    if not bool(requirements.get("function_calling")):
        return False
    import hashlib

    expected = hashlib.sha256(
        f"{(profile.provider or '').strip().lower()}:{(profile.model_name or '').strip()}".encode("utf-8")
    ).hexdigest()[:16]
    return record.model_digest == expected


async def run_probe_for_profile(
    db: AsyncSession,
    profile: ModelProfile,
    *,
    client: Any,
) -> ModelToolProfileSnapshotRecord:
    """执行固定用例集并落库（全过=ok；任一能力未证=failed，结果仍留痕）。"""
    snapshot = await run_probe(
        client,
        provider=(profile.provider or "").strip().lower(),
        model_name=(profile.model_name or "").strip(),
    )
    repository = ModelProbeSnapshotRepository(db)
    if snapshot.passed:
        return await repository.save(profile.id, snapshot)
    return await repository.save(
        profile.id,
        snapshot,
        status=PROBE_STATUS_FAILED,
        error_code="capability_unproven",
    )


async def auto_probe_profile(
    db: AsyncSession,
    profile: ModelProfile,
    *,
    cfg: Any,
    provider_settings: Mapping[str, str],
    timeout_s: float = AUTO_PROBE_TIMEOUT_S,
) -> ModelToolProfileSnapshotRecord | None:
    """模型配置保存后的自动探测（§8.2：随配置执行、结果持久化）。

    尽力而为：任何异常落失败快照，不抛出（配置保存不被探测阻断）；
    ``PA_AGENT_V2_MODEL_PROBE_ENABLED`` 关闭或 profile 不满足探测前提时跳过。
    """
    if not getattr(cfg, "agent_v2_model_probe_enabled", True):
        return None
    if not profile.enabled or not profile.native_tool_calls:
        return None
    if not (profile.model_name or "").strip():
        return None
    repository = ModelProbeSnapshotRepository(db)
    try:
        gateway = build_gateway_for_profile(
            profile,
            provider_settings,
            default_temperature=cfg.llm_temperature,
            default_context_length=cfg.llm_context_length,
            ollama_base_url=cfg.ollama_base_url,
        )
        snapshot = await asyncio.wait_for(
            run_probe(
                gateway,
                provider=(profile.provider or "").strip().lower(),
                model_name=(profile.model_name or "").strip(),
            ),
            timeout=timeout_s,
        )
        if snapshot.passed:
            return await repository.save(profile.id, snapshot)
        return await repository.save(
            profile.id,
            snapshot,
            status=PROBE_STATUS_FAILED,
            error_code="capability_unproven",
        )
    except asyncio.TimeoutError:
        return await repository.save_failed(
            profile.id,
            provider=(profile.provider or "").strip().lower(),
            model_name=(profile.model_name or "").strip(),
            error_code="probe_timeout",
        )
    except Exception:  # noqa: BLE001 - 探测失败不阻断配置保存
        return await repository.save_failed(
            profile.id,
            provider=(profile.provider or "").strip().lower(),
            model_name=(profile.model_name or "").strip(),
            error_code="probe_failed",
        )
