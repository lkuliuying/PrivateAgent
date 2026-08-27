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
from ..core.db import async_session_factory

#: 自动探测整体超时（本地 14B 6 用例约 30~120s；超时按失败快照落库）。
AUTO_PROBE_TIMEOUT_S = 240.0

PROBE_STATUS_OK = "ok"
PROBE_STATUS_FAILED = "failed"
PROBE_STATUS_RUNNING = "running"

#: 生产探测默认重复轮数——单次六题探测存在模型波动，多轮聚合降低误判。
PROBE_REPEATS = 2

# asyncio 事件循环只弱引用 Task；保留进程内强引用既避免后台探测被提前回收，
# 也给状态/重试端点一个可靠的“本进程确实仍在运行”事实。
_probe_tasks: dict[str, asyncio.Task[None]] = {}


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

    async def mark_running(
        self, profile: ModelProfile
    ) -> ModelToolProfileSnapshotRecord:
        """探测开始：先落 running 行（进度可见；异常中断时留下一条可辨识记录）。"""
        record = ModelToolProfileSnapshotRecord(
            profile_id=profile.id,
            provider=(profile.provider or "").strip().lower(),
            model_name=(profile.model_name or "").strip(),
            model_digest="",
            status=PROBE_STATUS_RUNNING,
            error_code=None,
            sample_count=0,
            pass_count=0,
            results_json=None,
            requirements_json=None,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

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
            .order_by(
                ModelToolProfileSnapshotRecord.created_at.desc(),
                ModelToolProfileSnapshotRecord.id.desc(),
            )
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
    return probe_snapshot_matches_profile(record, profile)


def probe_snapshot_matches_profile(
    record: ModelToolProfileSnapshotRecord,
    profile: ModelProfile,
) -> bool:
    """快照是否属于 profile 当前 provider/model 配置。"""
    provider = (profile.provider or "").strip().lower()
    model_name = (profile.model_name or "").strip()
    if record.provider != provider or record.model_name != model_name:
        return False
    if record.status != PROBE_STATUS_OK:
        return True
    import hashlib

    expected = hashlib.sha256(
        f"{provider}:{model_name}".encode("utf-8")
    ).hexdigest()[:16]
    return record.model_digest == expected


async def run_probe_for_profile(
    db: AsyncSession,
    profile: ModelProfile,
    *,
    client: Any,
    repeats: int = PROBE_REPEATS,
) -> ModelToolProfileSnapshotRecord:
    """执行固定用例集并落库（全过=ok；任一能力未证=failed，结果仍留痕）。"""
    snapshot = await run_probe(
        client,
        provider=(profile.provider or "").strip().lower(),
        model_name=(profile.model_name or "").strip(),
        repeats=repeats,
    )
    repository = ModelProbeSnapshotRepository(db)
    # 门禁语义：status=ok 当且仅当最小工具协议已证（function_calling）；
    # parallel/correction 等附加能力经 results/requirements 如实留痕，
    # 不作为基础工具面的门槛（AD-T04：已证能力才开启，未证不猜测）。
    if snapshot.requirements.function_calling:
        return await repository.save(profile.id, snapshot)
    return await repository.save(
        profile.id,
        snapshot,
        status=PROBE_STATUS_FAILED,
        error_code="capability_unproven",
    )


async def probe_gate_for_run(db: AsyncSession, model_profile_id: str | None) -> bool:
    """工具面门禁裁决（失败关闭，§8.2/AD-T04）。

    - 未绑定 profile 的 run（历史/非 coding）：保持既有行为（True）；
    - 绑定的 profile 已删除/查不到：False（不得放行副作用工具）；
    - profile 存在：仅当有效快照（§8.2 口径）时放行。
    """
    if model_profile_id is None:
        return True
    profile = await db.get(ModelProfile, model_profile_id)
    if profile is None:
        return False
    return await profile_tool_protocol_valid(db, profile)


class _GatewayProbeClient:
    """生产 ModelGateway → 探测客户端适配：补齐强制的 cancellation 参数。"""

    def __init__(self, gateway: Any) -> None:
        from personal_assistant.agents.runtime import CancellationToken

        self._gateway = gateway
        self._token = CancellationToken()

    async def complete(self, request: Any) -> Any:
        return await self._gateway.complete(request, cancellation=self._token)


def _probe_eligible(profile: ModelProfile) -> bool:
    return bool(
        profile.enabled
        and profile.native_tool_calls
        and (profile.model_name or "").strip()
    )


async def _probe_background(profile_id: str, cfg: Any) -> None:
    """后台探测任务：独立会话，全程不阻断调用方；任何异常落失败快照。"""
    from ..core.settings import SettingsService

    try:
        async with async_session_factory() as db:
            profile = await db.get(ModelProfile, profile_id)
            if profile is None or not _probe_eligible(profile):
                return
            repository = ModelProbeSnapshotRepository(db)
            await repository.mark_running(profile)
            provider_settings = await SettingsService(db).get_all()
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
                        _GatewayProbeClient(gateway),
                        provider=(profile.provider or "").strip().lower(),
                        model_name=(profile.model_name or "").strip(),
                        repeats=PROBE_REPEATS,
                    ),
                    timeout=AUTO_PROBE_TIMEOUT_S,
                )
                # 门禁语义同 run_probe_for_profile：最小工具协议已证即 ok。
                if snapshot.requirements.function_calling:
                    await repository.save(profile.id, snapshot)
                else:
                    await repository.save(
                        profile.id,
                        snapshot,
                        status=PROBE_STATUS_FAILED,
                        error_code="capability_unproven",
                    )
            except asyncio.TimeoutError:
                await repository.save_failed(
                    profile.id,
                    provider=(profile.provider or "").strip().lower(),
                    model_name=(profile.model_name or "").strip(),
                    error_code="probe_timeout",
                )
            except Exception:  # noqa: BLE001 - 探测失败落失败快照，不抛出
                await repository.save_failed(
                    profile.id,
                    provider=(profile.provider or "").strip().lower(),
                    model_name=(profile.model_name or "").strip(),
                    error_code="probe_failed",
                )
    except Exception:  # noqa: BLE001 - 后台任务不得向事件循环抛异常
        return


def start_probe_for_profile(
    db: AsyncSession,
    profile: ModelProfile,
    *,
    cfg: Any,
) -> bool:
    """调度后台探测（立即返回，不等待模型）。

    已有探测进行中（最新快照 running）时不重复调度；前提不满足或门控
    关闭时返回 False。进度/结果经最新快照行可查，重试入口再次调用本函数。
    """
    if not getattr(cfg, "agent_v2_model_probe_enabled", True):
        return False
    if not _probe_eligible(profile):
        return False
    existing = _probe_tasks.get(profile.id)
    if existing is not None and not existing.done():
        return False
    task = asyncio.get_running_loop().create_task(
        _probe_background(profile.id, cfg),
        name=f"model-tool-probe:{profile.id}",
    )
    _probe_tasks[profile.id] = task

    def _forget(completed: asyncio.Task[None], *, profile_id: str = profile.id) -> None:
        if _probe_tasks.get(profile_id) is completed:
            _probe_tasks.pop(profile_id, None)

    task.add_done_callback(_forget)
    return True


def probe_task_active(profile_id: str) -> bool:
    """当前进程是否确有该 profile 的后台探测任务。"""
    task = _probe_tasks.get(profile_id)
    return task is not None and not task.done()


async def cancel_probe_for_profile(profile_id: str) -> None:
    """删除 profile 前取消并回收对应后台探测，防止删除后再次写入孤儿快照。"""
    task = _probe_tasks.pop(profile_id, None)
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def auto_probe_profile(
    db: AsyncSession,
    profile: ModelProfile,
    *,
    cfg: Any,
    provider_settings: Mapping[str, str] | None = None,
    timeout_s: float = AUTO_PROBE_TIMEOUT_S,
) -> ModelToolProfileSnapshotRecord | None:
    """模型配置保存后的自动探测入口（§8.2：随配置执行、结果持久化）。

    v1.0 三次验收修复：探测改为**后台任务**，保存请求不再同步等待模型
    （本地 14B 可达分钟级）；进度/结果经最新快照行呈现，重试入口再次调用。
    已有探测进行中时不重复调度；返回 None 表示未新启动。
    """
    del provider_settings, timeout_s  # 兼容旧签名；后台任务自行取配置。
    start_probe_for_profile(db, profile, cfg=cfg)
    return None
