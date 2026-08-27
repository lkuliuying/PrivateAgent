"""v0.9.0 H1-D（计划 §5.8）：旧配置 → Coding model profile 幂等导入。

升级安装发现「全局 Provider 已配置且没有 Coding profile」时：

- 本地 Ollama 单一模型且受限 probe 通过 → 自动创建稳定 ID 的默认 profile
  （``ollama-default``），不静默扩大任何远程数据使用范围；
- 远程 Provider、凭据缺失、probe 不通过或存在歧义 → 不自动创建，
  导入状态置为待用户显式操作（一次性向导），由用户确认后导入。

红线：

- 流程幂等：已有任何 profile 时不再创建，重复调用返回既有默认项；
- Provider secret 不写入 profile（profile 只存非秘密路由事实）；
- 非交互路径（启动 reconcile）永不导入远程 profile。
"""

from __future__ import annotations

from ..logging_setup import get_logger
from .model_profile_probe import probe_model_profile
from .model_profiles import ModelProfile, ModelProfileService
from .settings import SettingsService

logger = get_logger(__name__)

IMPORT_STATE_KEY = "coding_profile_import_state"

# 稳定 ID（幂等锚点；重复导入不产生重复 profile）
_STABLE_PROFILE_IDS = {
    "ollama": "ollama-default",
    "openai": "openai-default",
    "claude": "claude-default",
}


class ModelProfileImportError(Exception):
    """导入失败（携带精确状态码，路由层映射 409）。"""

    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


async def _global_provider_facts(db) -> dict:
    """全局 Provider 配置事实（低基数；不含 secret 值本身以外的敏感项）。"""
    settings = await SettingsService(db).get_all()
    provider_type = (settings.get("provider_type") or "ollama").strip().lower()
    remote_enabled = settings.get("remote_provider_enabled", "false").lower() == "true"
    if provider_type == "openai":
        model_name = (settings.get("openai_model") or "").strip()
        credentials = bool(settings.get("openai_api_key"))
    elif provider_type == "claude":
        model_name = (settings.get("claude_model") or "").strip()
        credentials = bool(settings.get("claude_api_key"))
    else:
        provider_type = "ollama"
        model_name = (settings.get("llm_model") or "").strip()
        credentials = True  # 本地 Provider 无凭据概念
    return {
        "provider": provider_type,
        "model_name": model_name,
        "remote_enabled": remote_enabled,
        "credentials": credentials,
        "context_length": int(settings.get("llm_context_length") or 8192),
    }


async def evaluate_import_state(db) -> dict:
    """导入状态评估（供 /import-status 与启动 reconcile 共用）。

    返回 ``{import_state, reason_code, provider, model_available}``。
    """
    service = ModelProfileService(db)
    profiles = await service.list()
    if profiles:
        return {
            "import_state": "not_needed",
            "reason_code": None,
            "provider": None,
            "model_available": False,
        }
    facts = await _global_provider_facts(db)
    if not facts["model_name"]:
        # 全局 Provider 未配置模型：无导入源（正常走首启配置流程）
        return {
            "import_state": "not_needed",
            "reason_code": "no_global_provider",
            "provider": None,
            "model_available": False,
        }
    provider = facts["provider"]
    if provider != "ollama":
        if not facts["remote_enabled"]:
            reason = "feature_disabled"
        elif not facts["credentials"]:
            reason = "credentials_missing"
        else:
            # 远程外发必须用户显式确认（不静默扩大远程数据使用范围）
            reason = "remote_requires_confirmation"
        return {
            "import_state": "wizard",
            "reason_code": reason,
            "provider": provider,
            "model_available": False,
        }
    return {
        "import_state": "pending",
        "reason_code": None,
        "provider": provider,
        "model_available": True,
    }


async def _create_default_profile(
    db, *, provider: str, model_name: str, context_length: int, is_local: bool
) -> ModelProfile:
    service = ModelProfileService(db)
    profile_id = _STABLE_PROFILE_IDS[provider]
    profile = await service.upsert(
        profile_id,
        {
            "provider": provider,
            "display_name": model_name,
            "model_name": model_name,
            "is_local": is_local,
            "native_tool_calls": True,
            "supports_streaming": is_local,
            "context_tokens": context_length,
            "usage_reporting": True,
            "enabled": True,
        },
    )
    await service.set_default(profile_id)
    return await service.get(profile_id) or profile


async def import_legacy_provider_profile(
    db, *, interactive: bool
) -> dict:
    """把全局 Provider 配置导入为默认 Coding profile（幂等）。

    - 已有 profile → 直接返回既有默认项（不重复创建）；
    - ``interactive=False``（启动 reconcile）仅处理本地 Ollama，且要求
      受限 probe 通过；远程/歧义/失败一律跳过（交给一次性向导）；
    - ``interactive=True``（用户在向导中显式发起）可导入远程配置，
      但远程能力未启用或凭据缺失时失败关闭并返回精确状态码。
    """
    service = ModelProfileService(db)
    settings_service = SettingsService(db)
    existing = await service.list()
    if existing:
        default_profile = await service.get_default() or existing[0]
        return {
            "imported": False,
            "already_exists": True,
            "profile_id": default_profile.id,
            "error_code": None,
        }
    facts = await _global_provider_facts(db)
    provider = facts["provider"]
    model_name = facts["model_name"]
    if not model_name:
        raise ModelProfileImportError(
            "no_global_provider", "全局 Provider 尚未配置模型，无可导入来源"
        )
    if provider != "ollama":
        if not interactive:
            raise ModelProfileImportError(
                "remote_requires_confirmation",
                "远程 Provider 导入需要用户在向导中显式确认",
            )
        if not facts["remote_enabled"]:
            raise ModelProfileImportError(
                "feature_disabled", "远程 Provider 未启用，请先在设置中开启"
            )
        if not facts["credentials"]:
            raise ModelProfileImportError(
                "credentials_missing", "远程 Provider 凭据缺失，请先配置系统凭据"
            )
    profile = await _create_default_profile(
        db,
        provider=provider,
        model_name=model_name,
        context_length=facts["context_length"],
        is_local=(provider == "ollama"),
    )
    # 创建后受限探测验证（失败则回滚删除，不留下不可用的默认 profile）
    probe = await probe_model_profile(db, profile.id)
    if probe.status not in {"ok", "tools_unsupported"}:
        await service.delete(profile.id)
        raise ModelProfileImportError(probe.status, probe.detail or "探测未通过")
    await settings_service.update(
        {IMPORT_STATE_KEY: "imported" if interactive else "auto_imported"}
    )
    logger.info(
        "model profile imported",
        provider=provider,
        interactive=interactive,
        probe_status=probe.status,
    )
    return {
        "imported": True,
        "already_exists": False,
        "profile_id": profile.id,
        "error_code": None,
    }
