"""RAG 核心：文档解析、切分、向量化辅助、检索、引用生成。

- 解析：pypdf / python-docx / markdown / txt，扫描件 PDF 检测并提示
- 切分：按字符数 500 + overlap 80（中文友好）
- 检索：embed query → ChromaDB top-k → MySQL 回查切片原文与文档名
- 引用：文档名 + 片段序号

向量入库与原文入库由 workers/importer.py 编排；本模块提供能力与检索。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .provider import OllamaProvider
from .repo import DocChunkRepository, DocumentRepository
from .store_chroma import chroma_store

logger = get_logger(__name__)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


# ---------------- 解析 ----------------
def _parse_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages).strip()


def _parse_docx(path: str) -> str:
    from docx import Document

    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs).strip()


def _parse_text_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


PARSERS = {
    ".pdf": _parse_pdf,
    ".docx": _parse_docx,
    ".md": _parse_text_file,
    ".markdown": _parse_text_file,
    ".txt": _parse_text_file,
}


def is_scanned_pdf(path: str, min_chars_per_page: int = 50) -> bool:
    """粗略检测扫描件 PDF：平均每页可提取文本极少。"""
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        n = len(reader.pages)
        if n == 0:
            return False
        total = sum(len((p.extract_text() or "").strip()) for p in reader.pages)
        return total / n < min_chars_per_page
    except Exception:  # noqa: BLE001
        return False


def parse_document(path: str) -> str:
    """根据扩展名解析文档为纯文本。不支持类型或扫描件 PDF 抛 ValueError。"""
    ext = Path(path).suffix.lower()
    parser = PARSERS.get(ext)
    if not parser:
        raise ValueError(f"暂不支持的文件类型: {ext}")
    if ext == ".pdf" and is_scanned_pdf(path):
        raise ValueError("暂不支持扫描件 PDF（第一阶段未集成 OCR）")
    text = parser(path)
    if not text:
        raise ValueError("文档解析结果为空（可能是扫描件或空文档）")
    return text


# ---------------- 切分 ----------------
def split_text(
    text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """按字符数切分，相邻切片带 overlap。"""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if c]


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------- 检索 + 引用 ----------------
@dataclass
class RetrievedChunk:
    chunk_id: int
    doc_id: int
    doc_name: str
    ordinal: int
    content: str


class RagService:
    def __init__(
        self, db: AsyncSession, provider: OllamaProvider | None = None
    ) -> None:
        self.db = db
        self._provider = provider
        self.docs = DocumentRepository(db)
        self.chunk_repo = DocChunkRepository(db)

    async def _get_provider(self) -> OllamaProvider:
        """嵌入模型从 settings 读取（支持运行时调整）。"""
        if self._provider is not None:
            return self._provider
        from .settings import SettingsService

        s = await SettingsService(self.db).get_all()
        return OllamaProvider(embed_model=s["embed_model"])

    async def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """检索与 query 最相关的切片，按相似度降序返回。"""
        provider = await self._get_provider()
        qvec = await provider.embed_one(query)
        chunk_ids = await chroma_store.query(qvec, top_k=top_k)
        if not chunk_ids:
            return []

        chunks_map = await self.chunk_repo.get_by_ids(chunk_ids)
        # 缓存 doc 查询，避免重复
        doc_cache: dict[int, str] = {}
        results: list[RetrievedChunk] = []
        for cid in chunk_ids:
            c = chunks_map.get(cid)
            if not c:
                continue
            if c.doc_id not in doc_cache:
                doc = await self.docs.get(c.doc_id)
                doc_cache[c.doc_id] = doc.name if doc else "(已删除)"
            results.append(
                RetrievedChunk(
                    chunk_id=c.id,
                    doc_id=c.doc_id,
                    doc_name=doc_cache[c.doc_id],
                    ordinal=c.ordinal,
                    content=c.content,
                )
            )
        return results

    @staticmethod
    def build_rag_messages(
        query: str, chunks: list[RetrievedChunk]
    ) -> list[dict[str, str]]:
        """构造带知识库上下文的 prompt（不含历史，历史由 ChatService 注入）。"""
        context = "\n\n".join(
            f"[来源：{c.doc_name} · 片段{c.ordinal}]\n{c.content}" for c in chunks
        )
        system = (
            "你是一个有用的私人助手。请根据下方「参考资料」回答用户问题。"
            "只能基于参考资料中的内容作答，不要编造资料中没有的信息。"
            "如果参考资料不足以回答，请明确说明「未在知识库中找到相关资料」。"
        )
        return [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"参考资料：\n{context}\n\n问题：{query}",
            },
        ]

    @staticmethod
    def format_sources(chunks: list[RetrievedChunk]) -> list[dict]:
        """生成前端引用展示用的来源列表。"""
        return [
            {"doc_name": c.doc_name, "ordinal": c.ordinal, "chunk_id": c.chunk_id}
            for c in chunks
        ]
