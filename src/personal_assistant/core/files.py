"""文件操作共享逻辑：摘要、目录扫描。

供 api/routes_files.py（用户直接调用的文件处理路由）与 core/tools.py
（LLM 触发的 summarize_file 工具）复用，避免摘要逻辑两处重复。

授权校验：所有操作前先 assert_trusted，只允许访问 trusted_paths 中的路径。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from .permissions import assert_trusted
from .provider import OllamaProvider
from .rag import parse_document
from .repo_tools import TrustedPathRepository
from .settings import SettingsService

MAX_FILE_BYTES = 30 * 1024 * 1024  # 30MB
MAX_CONTENT_CHARS = 50000  # 喂给 LLM 的内容上限
READABLE_EXT = {".txt", ".md", ".markdown", ".pdf", ".docx"}
SCAN_MAX_FILES = 200  # 目录批量导入文件数上限


async def summarize_path(db: AsyncSession, path: str) -> dict:
    """总结已授权文件：校验授权/类型/大小 → 解析 → LLM 摘要。

    抛 PermissionError_（未授权）、ValueError（文件/类型/大小问题）。
    """
    trusted = await TrustedPathRepository(db).all_paths()
    assert_trusted(path, trusted)
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise ValueError("文件不存在或不是文件")
    if p.suffix.lower() not in READABLE_EXT:
        raise ValueError(f"仅支持 {sorted(READABLE_EXT)} 文件")
    size = p.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"文件过大（{size} 字节，上限 {MAX_FILE_BYTES} 字节）")
    content = await asyncio.to_thread(parse_document, str(p))
    truncated = len(content) > MAX_CONTENT_CHARS
    if truncated:
        content = content[:MAX_CONTENT_CHARS]
    s = await SettingsService(db).get_all()
    provider = OllamaProvider(
        llm_model=s["llm_model"],
        temperature=float(s["llm_temperature"]),
        context_length=int(s["llm_context_length"]),
    )
    summary = await provider.chat(
        [
            {"role": "system", "content": "请用中文简洁总结以下文件内容，提炼要点，分条陈述。"},
            {"role": "user", "content": f"文件名：{p.name}\n\n内容：\n{content}"},
        ]
    )
    return {
        "summary": summary,
        "name": p.name,
        "path": str(p),
        "size_bytes": size,
        "truncated": truncated,
    }


def scan_directory(path: str) -> dict:
    """扫描目录下可处理文件（READABLE_EXT），上限 SCAN_MAX_FILES。

    抛 ValueError（目录不存在/非目录）。授权校验由调用方先做。
    返回 {path, files:[{path,name,size_bytes}], count, truncated}。
    """
    p = Path(path)
    if not p.exists() or not p.is_dir():
        raise ValueError("目录不存在或不是目录")
    files: list[dict] = []
    truncated = False
    # rglob 递归扫描；排序保证结果稳定
    for f in sorted(p.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() not in READABLE_EXT:
            continue
        if len(files) >= SCAN_MAX_FILES:
            truncated = True
            break
        files.append(
            {"path": str(f), "name": f.name, "size_bytes": f.stat().st_size}
        )
    return {
        "path": str(p),
        "files": files,
        "count": len(files),
        "truncated": truncated,
    }
