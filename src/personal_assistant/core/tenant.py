"""请求级租户上下文。

普通用户请求设置 ``current_user_id``；服务端内部任务和本地维护令牌保持
``None``，因此可以执行明确授权的全局维护。管理员汇总必须显式使用
``without_tenant_scope``，避免业务代码无意绕过隔离。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

current_user_id: ContextVar[int | None] = ContextVar(
    "personal_assistant_current_user_id", default=None
)
tenant_scope_bypassed: ContextVar[bool] = ContextVar(
    "personal_assistant_tenant_scope_bypassed", default=False
)


def enter_tenant(user_id: int | None) -> Token[int | None]:
    """进入一个请求的租户上下文，并返回可用于恢复的 token。"""
    return current_user_id.set(user_id)


def exit_tenant(token: Token[int | None]) -> None:
    current_user_id.reset(token)


@contextmanager
def without_tenant_scope() -> Iterator[None]:
    """仅供管理员汇总或后台维护显式读取跨用户数据。"""
    token = tenant_scope_bypassed.set(True)
    try:
        yield
    finally:
        tenant_scope_bypassed.reset(token)
