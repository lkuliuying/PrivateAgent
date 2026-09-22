"""面向工作区浏览面板的只读文件接口，复用现有路径与读取保护。"""
from pathlib import Path

from . import files, policy


def preview(root: Path, relative: str, offset: int = 0, limit: int = 32000, version: str | None = None) -> dict:
    policy.file_scope(root, relative, "readonly")
    raw, _ = files.safe_bytes(root, relative)
    digest = files.digest(raw)
    if version is not None and digest != version:
        raise ValueError("文件已变化，请刷新后重新预览")
    text = raw.decode("utf-8-sig")
    if not 0 <= offset <= len(text) or not 1 <= limit <= 32000:
        raise ValueError("文件预览范围无效")
    end = min(len(text), offset + limit)
    return {"rel_path": relative, "content": text[offset:end], "sha256": digest,
            "offset": offset, "next_offset": end if end < len(text) else None, "total_chars": len(text)}
