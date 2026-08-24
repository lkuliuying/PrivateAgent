"""v0.9.0 H1-D（计划 §5.8）：模型 profile 受限探测。

验证 Provider 可达与模型存在性，形成结构化、可审计的状态码；**工具调用
能力不按模型名称推断**（能力是 profile 显式声明事实，探测只如实报告声明）。

状态码词汇（冻结）：

- ``ok``：Provider 可达且模型存在（claude 无列表端点时仅验证凭据存在）；
- ``profile_disabled``：profile 已停用；
- ``model_route_missing``：profile 缺少具体模型路由字段（model_name）；
- ``tools_unsupported``：profile 未声明原生工具调用（只读问答，非 Coding 默认）；
- ``feature_disabled``：远程 Provider 能力未启用（远程 profile）；
- ``credentials_missing``：远程 Provider 凭据缺失；
- ``provider_unreachable``：Provider 连接失败/超时；
- ``model_missing``：Provider 可达但模型不存在；
- ``probe_failed``：其他探测异常（不猜测原因）。

红线：本模块不接收、不返回、不记录任何 secret；探测结果只含低基数事实。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from ..config import settings as cfg
from ..logging_setup import get_logger
from .model_profiles import ModelProfileService
from .settings import SettingsService

logger = get_logger(__name__)

PROBE_STATUS_CODES = frozenset(
    {
        "ok",
        "profile_disabled",
        "model_route_missing",
        "tools_unsupported",
        "feature_disabled",
        "credentials_missing",
        "provider_unreachable",
        "model_missing",
        "probe_failed",
    }
)

_OLLAMA_TIMEOUT_SECONDS = 3.0
_REMOTE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ModelProfileProbeResult:
    """受限探测结果（低基数；无 secret、无完整 URL 之外的敏感内容）。"""

    status: str
    provider_reachable: bool | None = None
    model_exists: bool | None = None
    native_tool_calls: bool | None = None
    detail: str = ""

    def to_payload(self) -> dict:
        return {
            "status": self.status,
            "provider_reachable": self.provider_reachable,
            "model_exists": self.model_exists,
            "native_tool_calls": self.native_tool_calls,
            "detail": self.detail,
        }


def _ollama_model_in_tags(model_name: str, names: list[str]) -> bool:
    """模型存在性（兼容 ``:latest`` 隐式后缀，与 OllamaProvider 同口径）。"""
    wanted = model_name.strip()
    for name in names:
        if name == wanted:
            return True
        if f"{wanted}:latest" == name:
            return True
    return False


async def _probe_ollama(model_name: str) -> ModelProfileProbeResult:
    url = f"{cfg.ollama_base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(
            timeout=_OLLAMA_TIMEOUT_SECONDS, trust_env=False
        ) as client:
            response = await client.get(url)
    except (httpx.TimeoutException, httpx.HTTPError, OSError):
        return ModelProfileProbeResult(
            status="provider_unreachable",
            provider_reachable=False,
            detail="Ollama 服务不可达（检查服务是否启动与连接地址）",
        )
    if response.status_code != 200:
        return ModelProfileProbeResult(
            status="provider_unreachable",
            provider_reachable=False,
            detail=f"Ollama 响应异常（HTTP {response.status_code}）",
        )
    try:
        names = [str(item.get("name", "")) for item in response.json().get("models", [])]
    except (ValueError, AttributeError):
        return ModelProfileProbeResult(
            status="probe_failed",
            provider_reachable=True,
            detail="Ollama 模型列表响应格式异常",
        )
    exists = _ollama_model_in_tags(model_name, names)
    if not exists:
        return ModelProfileProbeResult(
            status="model_missing",
            provider_reachable=True,
            model_exists=False,
            detail="Ollama 可达，但该模型未安装（请先拉取模型）",
        )
    return ModelProfileProbeResult(
        status="ok",
        provider_reachable=True,
        model_exists=True,
    )


async def _probe_openai(
    model_name: str, settings: dict[str, str]
) -> ModelProfileProbeResult:
    if settings.get("remote_provider_enabled", "false").lower() != "true":
        return ModelProfileProbeResult(
            status="feature_disabled",
            detail="远程 Provider 未启用（请先在设置中开启）",
        )
    api_key = settings.get("openai_api_key") or ""
    if not api_key:
        return ModelProfileProbeResult(
            status="credentials_missing",
            detail="OpenAI 凭据缺失（请在系统凭据中配置）",
        )
    base_url = settings.get("openai_base_url") or "https://api.openai.com/v1"
    url = f"{base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=_REMOTE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {api_key}"}
            )
    except (httpx.TimeoutException, httpx.HTTPError, OSError):
        return ModelProfileProbeResult(
            status="provider_unreachable",
            provider_reachable=False,
            detail="OpenAI 兼容端点不可达",
        )
    if response.status_code in (401, 403):
        return ModelProfileProbeResult(
            status="credentials_missing",
            provider_reachable=True,
            detail="OpenAI 凭据无效（认证失败）",
        )
    if response.status_code != 200:
        return ModelProfileProbeResult(
            status="provider_unreachable",
            provider_reachable=False,
            detail=f"OpenAI 兼容端点响应异常（HTTP {response.status_code}）",
        )
    try:
        ids = [str(item.get("id", "")) for item in response.json().get("data", [])]
    except (ValueError, AttributeError):
        return ModelProfileProbeResult(
            status="probe_failed",
            provider_reachable=True,
            detail="OpenAI 模型列表响应格式异常",
        )
    exists = model_name.strip() in ids
    return ModelProfileProbeResult(
        status="ok" if exists else "model_missing",
        provider_reachable=True,
        model_exists=exists,
        detail="" if exists else "端点可达，但该模型不在可用列表",
    )


async def probe_model_profile(db, profile_id: str) -> ModelProfileProbeResult:
    """对单个 profile 执行受限探测（幂等只读，不修改任何状态）。"""
    profile = await ModelProfileService(db).get(profile_id)
    if profile is None:
        return ModelProfileProbeResult(
            status="profile_disabled", detail="模型 profile 不存在"
        )
    if not profile.enabled:
        return ModelProfileProbeResult(
            status="profile_disabled", detail="模型 profile 已停用"
        )
    if not (profile.model_name or "").strip():
        return ModelProfileProbeResult(
            status="model_route_missing",
            detail="profile 缺少具体模型路由字段（model_name）",
        )
    settings = await SettingsService(db).get_all()
    provider = (profile.provider or "").strip().lower()
    model_name = profile.model_name.strip()
    try:
        if profile.is_local or provider == "ollama":
            result = await _probe_ollama(model_name)
        elif provider == "openai":
            result = await _probe_openai(model_name, settings)
        elif provider == "claude":
            if settings.get("remote_provider_enabled", "false").lower() != "true":
                result = ModelProfileProbeResult(
                    status="feature_disabled",
                    detail="远程 Provider 未启用（请先在设置中开启）",
                )
            elif not (settings.get("claude_api_key") or ""):
                result = ModelProfileProbeResult(
                    status="credentials_missing",
                    detail="Claude 凭据缺失（请在系统凭据中配置）",
                )
            else:
                # Claude 无模型列表端点：凭据存在即可；不发起计费请求。
                result = ModelProfileProbeResult(
                    status="ok",
                    provider_reachable=None,
                    model_exists=None,
                    detail="凭据已配置（Claude 无模型列表端点，未验证模型存在性）",
                )
        else:
            result = ModelProfileProbeResult(
                status="probe_failed", detail=f"未知 provider: {provider}"
            )
    except Exception:  # noqa: BLE001 - 探测异常收敛为 probe_failed，不泄露细节
        logger.warning("model profile probe failed", profile_id=profile_id)
        result = ModelProfileProbeResult(
            status="probe_failed", detail="探测过程异常，请重试"
        )
    # 工具能力是显式声明事实：探测不按名称推断，只如实标记不可作为 Coding 默认
    if result.status == "ok" and not profile.native_tool_calls:
        return ModelProfileProbeResult(
            status="tools_unsupported",
            provider_reachable=result.provider_reachable,
            model_exists=result.model_exists,
            native_tool_calls=False,
            detail="Provider/模型可用，但未声明原生工具调用（只能用于只读问答）",
        )
    return ModelProfileProbeResult(
        status=result.status,
        provider_reachable=result.provider_reachable,
        model_exists=result.model_exists,
        native_tool_calls=profile.native_tool_calls,
        detail=result.detail,
    )


async def probe_with_timeout(db, profile_id: str) -> ModelProfileProbeResult:
    """探测整体超时兜底（防止慢端点拖住设置页）。"""
    try:
        return await asyncio.wait_for(probe_model_profile(db, profile_id), 15)
    except TimeoutError:
        return ModelProfileProbeResult(
            status="provider_unreachable",
            provider_reachable=False,
            detail="探测超时（15 秒）",
        )
