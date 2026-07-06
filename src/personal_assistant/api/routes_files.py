"""文件授权与处理路由（第二阶段 M1/M2）。

- POST /files/authorize  记录用户授权的路径到 trusted_paths（去重）
- GET  /files/trusted    列出已授权路径
- POST /files/summarize  总结已授权文件（LLM 摘要）
- GET  /files/scan       扫描授权目录下可处理文件（上限 200）
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_session
from ..core.files import scan_directory, summarize_path
from ..core.permissions import PermissionError_, assert_trusted
from ..core.repo_tools import TrustedPathRepository

router = APIRouter(tags=["files"])


class TrustedPathOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    path: str
    kind: str
    granted_at: datetime


class AuthorizeRequest(BaseModel):
    path: str
    kind: str = "file"

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, v: str) -> str:
        if v not in ("file", "directory"):
            raise ValueError("kind 必须为 file 或 directory")
        return v

    @field_validator("path")
    @classmethod
    def _check_path(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("path 不能为空")
        # 必须为绝对路径：相对路径会被 is_trusted_path 按后端 CWD 解析，
        # 授权到非预期位置（含 .env/配置）。.resolve() 也会锚定 CWD，故直接拒绝。
        p = Path(v).expanduser()
        if not p.is_absolute():
            raise ValueError("path 必须为绝对路径")
        return str(p)


class SummarizeRequest(BaseModel):
    path: str


class SummarizeResponse(BaseModel):
    summary: str
    name: str
    path: str
    size_bytes: int
    truncated: bool


class ScanFile(BaseModel):
    path: str
    name: str
    size_bytes: int


class ScanResponse(BaseModel):
    path: str
    files: list[ScanFile]
    count: int
    truncated: bool


@router.post("/files/authorize", response_model=TrustedPathOut, status_code=201)
async def authorize(req: AuthorizeRequest, db: AsyncSession = Depends(get_session)):
    try:
        return await TrustedPathRepository(db).authorize(req.path, req.kind)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"授权失败: {e}")


@router.get("/files/trusted", response_model=list[TrustedPathOut])
async def list_trusted(db: AsyncSession = Depends(get_session)):
    return await TrustedPathRepository(db).list()


@router.post("/files/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest, db: AsyncSession = Depends(get_session)):
    """总结已授权文件。授权/类型/大小校验失败返回 403/400。"""
    try:
        # LLM 摘要可能较慢，设 120s 超时避免前端长期挂起
        return await asyncio.wait_for(summarize_path(db, req.path), timeout=120)
    except PermissionError_:
        raise HTTPException(403, f"路径未授权或越界: {req.path}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except asyncio.TimeoutError:
        raise HTTPException(504, "总结超时，请稍后重试")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"总结失败: {e}")


@router.get("/files/scan", response_model=ScanResponse)
async def scan(
    path: str = Query(..., description="已授权的目录绝对路径"),
    db: AsyncSession = Depends(get_session),
):
    """扫描授权目录下可处理文件（.txt/.md/.markdown/.pdf/.docx），上限 200 个。"""
    trusted = await TrustedPathRepository(db).all_paths()
    try:
        assert_trusted(path, trusted)
    except PermissionError_:
        raise HTTPException(403, f"路径未授权或越界: {path}")
    try:
        return await asyncio.to_thread(scan_directory, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
