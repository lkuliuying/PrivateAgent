"""异步数据库引擎与 Session 工厂。"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event, inspect, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, with_loader_criteria

from ..config import settings
from .tenant import current_user_id, tenant_scope_bypassed

# pool_pre_ping：连接前 ping，避免 MySQL 断连后首请求失败
# pool_recycle：MySQL 默认 wait_timeout 8h，这里保守回收
# init_command：每条新连接设会话时区为 UTC，使 CURRENT_TIMESTAMP 与 Python naive UTC
#   （core/timeutil.utcnow）一致，避免 activities 等表内时间戳时区偏移。
engine = create_async_engine(
    settings.db_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True,
    connect_args={"init_command": "SET time_zone='+00:00'"},
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(execute_state) -> None:
    """对普通用户的 ORM SELECT/UPDATE/DELETE 自动附加 owner 条件。"""
    user_id = current_user_id.get()
    if user_id is None or tenant_scope_bypassed.get():
        return
    if execute_state.is_select:
        statement = execute_state.statement
        for mapper in execute_state.all_mappers:
            model = mapper.class_
            if getattr(model, "__tenant_scoped__", True):
                statement = statement.options(
                    with_loader_criteria(
                        model,
                        lambda entity: entity.owner_user_id == user_id,
                        include_aliases=True,
                    )
                )
        execute_state.statement = statement
        return
    if execute_state.is_update or execute_state.is_delete:
        mapper = execute_state.bind_mapper
        if mapper is not None and getattr(
            mapper.class_, "__tenant_scoped__", True
        ):
            execute_state.statement = execute_state.statement.where(
                mapper.class_.owner_user_id == user_id
            )


@event.listens_for(Session, "before_flush")
def _assign_tenant_owner(session: Session, _flush_context, _instances) -> None:
    """新建业务行从请求或父记录继承 owner，避免后台派生数据失去归属。"""
    user_id = current_user_id.get()
    if tenant_scope_bypassed.get():
        return
    for item in session.new:
        if not getattr(type(item), "__tenant_scoped__", True) or getattr(
            item, "owner_user_id", None
        ) is not None:
            continue
        owner_id = user_id
        if owner_id is None:
            mapper = inspect(item).mapper
            for relationship in mapper.relationships:
                if relationship.uselist:
                    continue
                parent = getattr(item, relationship.key, None)
                parent_owner = getattr(parent, "owner_user_id", None)
                if parent_owner is not None:
                    owner_id = int(parent_owner)
                    break
            if owner_id is None:
                for foreign_key in mapper.local_table.foreign_keys:
                    parent_table = foreign_key.column.table
                    if "owner_user_id" not in parent_table.c:
                        continue
                    local_value = getattr(item, foreign_key.parent.key, None)
                    if local_value is None:
                        continue
                    parent_owner = session.connection().execute(
                        select(parent_table.c.owner_user_id).where(
                            foreign_key.column == local_value
                        )
                    ).scalar_one_or_none()
                    if parent_owner is not None:
                        owner_id = int(parent_owner)
                        break
        if owner_id is not None:
            item.owner_user_id = owner_id


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供一个异步 Session，请求结束自动关闭。"""
    async with async_session_factory() as session:
        yield session
