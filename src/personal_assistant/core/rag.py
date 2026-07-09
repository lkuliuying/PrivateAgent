"""RAG 核心：文档解析、切分、向量化辅助、检索、引用生成。

- 解析：pypdf / python-docx / markdown / txt，扫描件 PDF 检测并提示
- 切分：按字符数 500 + overlap 80（中文友好）
- 检索：向量 + 关键词混合（见 hybrid_retrieval），返回带命中原因的切片
- 引用：文档名 + 片段序号 + 命中关键词

向量入库与原文入库由 workers/importer.py 编排；本模块提供能力与检索。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .provider import OllamaProvider, ProviderRouter

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


class NeedsOcrError(ValueError):
    """扫描件 PDF 需 OCR（第七阶段 M3）：importer 捕获后创建 OCR job 而非 hard fail。"""


def parse_document(path: str) -> str:
    """根据扩展名解析文档为纯文本。不支持类型或扫描件 PDF 抛 ValueError。"""
    ext = Path(path).suffix.lower()
    parser = PARSERS.get(ext)
    if not parser:
        raise ValueError(f"暂不支持的文件类型: {ext}")
    if ext == ".pdf" and is_scanned_pdf(path):
        raise NeedsOcrError("扫描件 PDF 需 OCR 处理")
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


def extract_heading(text: str, max_len: int = 512) -> str | None:
    """从切片文本提取标题：首个非空行（markdown 标题或首句），截断保护。

    供引用展示与命中定位用；不参与召回算法。
    """
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:max_len]
    return None


# ---------------- 检索 + 引用 ----------------
@dataclass
class RetrievedChunk:
    chunk_id: int
    doc_id: int
    doc_name: str
    ordinal: int
    content: str
    heading: str | None = None
    score: float = 0.0
    matched_via: list[str] | None = None
    matched_keywords: list[str] | None = None


class RagService:
    def __init__(
        self, db: AsyncSession, provider: OllamaProvider | None = None
    ) -> None:
        self.db = db
        self._provider = provider

    async def _get_provider(self) -> OllamaProvider:
        """嵌入模型从 settings 读取（支持运行时调整）。"""
        if self._provider is not None:
            return self._provider
        from .settings import SettingsService

        s = await SettingsService(self.db).get_all()
        return ProviderRouter(s).embedding_provider()

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters=None,
    ) -> list[RetrievedChunk]:
        """混合检索（向量 + 关键词 + RRF + rerank），返回带命中原因的切片。

        filters 为 RetrievalFilters 或 None（默认仅 enabled=True）。
        禁用文档在两路召回均被排除。
        """
        from .hybrid_retrieval import HybridRetriever, RetrievalFilters

        flt = filters if isinstance(filters, RetrievalFilters) else RetrievalFilters()
        retriever = HybridRetriever(self.db, provider=self._provider)
        try:
            results = await retriever.retrieve(query, top_k=top_k, filters=flt)
        except Exception:  # noqa: BLE001
            logger.exception("hybrid retrieve failed, falling back to empty")
            return []
        return [
            RetrievedChunk(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                doc_name=r.doc_name,
                ordinal=r.ordinal,
                content=r.content,
                heading=r.heading,
                score=r.score,
                matched_via=list(r.matched_via),
                matched_keywords=list(r.matched_keywords),
            )
            for r in results
        ]

    @staticmethod
    def build_rag_messages(
        query: str, chunks: list[RetrievedChunk]
    ) -> list[dict[str, str]]:
        """构造带知识库上下文的 prompt（不含历史，历史由 ChatService 注入）。

        引用标注命中关键词，便于用户判断相关性。
        """
        context = "\n\n".join(
            f"[来源：{c.doc_name} · 片段{c.ordinal}"
            + (f" · 命中：{', '.join(c.matched_keywords)}" if c.matched_keywords else "")
            + f"]\n{c.content}"
            for c in chunks
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
        """生成前端引用展示用的来源列表（含命中原因与分数）。"""
        return [
            {
                "doc_name": c.doc_name,
                "ordinal": c.ordinal,
                "chunk_id": c.chunk_id,
                "heading": c.heading,
                "score": round(c.score, 4) if c.score else None,
                "matched_via": c.matched_via or [],
                "matched_keywords": c.matched_keywords or [],
            }
            for c in chunks
        ]
