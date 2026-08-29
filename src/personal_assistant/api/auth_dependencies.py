"""认证与管理员权限依赖。"""
from __future__ import annotations

from fastapi import HTTPException, Request, status

from ..core.auth import Principal


def current_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal) or principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def admin_principal(request: Request) -> Principal:
    principal = current_principal(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return principal
