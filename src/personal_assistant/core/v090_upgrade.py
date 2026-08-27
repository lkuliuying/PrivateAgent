"""v0.9.0 H1 升级契约：启动/退出时的一次性兼容处置。

- 升级安装：已有项目幂等补建 root workspace（计划 §3.2 / H1 任务 3）；
- full_access 授予自动失效：进程重启 = 上一进程生命周期的授予全部回收
  （H0 §6.3 失败关闭），退出应用时同样回收。
- v0.9.0 H1-D（计划 §5.8）：旧配置 → Coding profile 幂等导入——已有全局
  Provider 配置但 profile 为空的旧安装，本地 Ollama 受限 probe 通过时自动
  创建稳定 ID 默认 profile；远程/歧义/失败交给一次性向导（不静默导入）；
  同时幂等回填既有 profile 缺失的具体模型路由字段。

全部动作幂等、additive，失败只记录日志不阻断启动。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import settings
from ..logging_setup import get_logger
from .models import Project

logger = get_logger(__name__)


async def ensure_root_workspaces_for_projects(db: AsyncSession) -> int:
    """为全部 active 项目幂等补建 root workspace；返回处理数量。"""
    from .projects import ProjectService

    result = await db.execute(
        select(Project).where(Project.status == "active")
    )
    projects = list(result.scalars().all())
    svc = ProjectService(db)
    count = 0
    for project in projects:
        try:
            await svc._ensure_workspace(project)
            await db.commit()
            count += 1
        except Exception:  # noqa: BLE001 - 升级补建失败不阻断启动
            await db.rollback()
            logger.warning(
                "root workspace ensure failed", project_id=project.id
            )
    return count


async def reconcile_model_profiles(db: AsyncSession) -> None:
    """v0.9.0 H1-D（§5.8）：启动幂等处置 Coding model profile。

    1. 既有 profile 缺失 ``model_name`` 时，从全局 Provider 配置幂等回填；
    2. profile 为空且全局已配置：非交互导入（仅本地 Ollama，受限 probe
       通过才创建）；远程/凭据缺失/歧义/失败 → 保持待导入状态，由前端
       一次性向导承接（不静默扩大远程数据使用范围）。
    """
    from .model_profile_import import (
        ModelProfileImportError,
        _global_provider_facts,
        import_legacy_provider_profile,
    )
    from .model_profiles import ModelProfileService

    service = ModelProfileService(db)
    facts = await _global_provider_facts(db)
    if facts["model_name"]:
        backfilled = await service.backfill_model_name(
            facts["provider"], facts["model_name"]
        )
        if backfilled:
            logger.info(
                "v0.9.0 H1-D model_name backfill",
                provider=facts["provider"],
                count=backfilled,
            )
    if not await service.list():
        try:
            result = await import_legacy_provider_profile(db, interactive=False)
            if result.get("imported"):
                logger.info(
                    "v0.9.0 H1-D default profile auto-imported",
                    profile_id=result.get("profile_id"),
                )
        except ModelProfileImportError as exc:
            # 非交互路径不处理：交给一次性向导（低基数日志，不含敏感内容）
            logger.info(
                "v0.9.0 H1-D profile import deferred to wizard",
                reason=exc.error_code,
            )


async def reconcile_v090_upgrade(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """启动 reconcile：workspace 补建 + full_access 授予回收 + profile 导入。"""
    try:
        async with factory() as db:
            if settings.project_bound_runs_enabled:
                count = await ensure_root_workspaces_for_projects(db)
                logger.info("v0.9.0 root workspace reconcile", projects=count)
            if settings.coding_full_access_enabled:
                from .full_access import FullAccessGrantService

                revoked = await FullAccessGrantService(db).revoke_all_on_app_exit()
                await db.commit()
                if revoked:
                    logger.info(
                        "v0.9.0 full_access grants revoked on restart",
                        count=revoked,
                    )
            if settings.coding_permission_models_enabled:
                await reconcile_model_profiles(db)
    except Exception:  # noqa: BLE001 - reconcile 失败不阻断启动
        logger.exception("v0.9.0 upgrade reconcile failed")


async def shutdown_v090(factory: async_sessionmaker[AsyncSession]) -> None:
    """退出应用：回收全部未撤销 full_access 授予（自动失效规则）。"""
    if not settings.coding_full_access_enabled:
        return
    try:
        async with factory() as db:
            from .full_access import FullAccessGrantService

            revoked = await FullAccessGrantService(db).revoke_all_on_app_exit()
            await db.commit()
            if revoked:
                logger.info(
                    "v0.9.0 full_access grants revoked on exit", count=revoked
                )
    except Exception:  # noqa: BLE001 - 退出回收失败只记录
        logger.exception("v0.9.0 shutdown grant revoke failed")
