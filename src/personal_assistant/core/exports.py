"""文档工作台服务：章节摘要 / 多文档对比 / 术语表 / Markdown 导出 / 笔记入库。

生成类（摘要/对比/术语表）基于文档切片为 LLM 提供上下文，输出 JSON。
导出（export_markdown）与笔记入库（import_note_to_kb）为写入操作，
经授权路径校验（assert_trusted）并默认新文件名避免覆盖。

复用 learning.py 的 JSON 解析助手（parse_json_array/object）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..logging_setup import get_logger
from .learning import parse_json_array, parse_json_object
from .permissions import assert_trusted
from .provider import OllamaProvider, ProviderError
from .repo import DocChunkRepository, DocumentRepository
from .repo_tools import TrustedPathRepository
from .settings import SettingsService

logger = get_logger(__name__)

MAX_EXPORT_BYTES = 2 * 1024 * 1024  # 单次导出内容上限
MAX_COMPARE_DOCS = 5
MAX_SECTION_CONTEXT_CHARS = 8000


class DocNotFound(LookupError):
    """文档不存在。"""


class ExportService:
    def __init__(self, db: AsyncSession, provider: OllamaProvider | None = None) -> None:
        self.db = db
        self._provider = provider
        self.docs = DocumentRepository(db)
        self.chunk_repo = DocChunkRepository(db)

    async def _get_provider(self) -> OllamaProvider:
        if self._provider is not None:
            return self._provider
        s = await SettingsService(self.db).get_all()
        return OllamaProvider(
            llm_model=s["llm_model"],
            temperature=float(s["llm_temperature"]),
            context_length=int(s["llm_context_length"]),
        )

    async def _doc_context(self, doc_id: int) -> tuple[str, str]:
        """返回 (doc_name, 拼接的切片上下文)。"""
        doc = await self.docs.get(doc_id)
        if doc is None:
            raise DocNotFound(f"文档不存在: {doc_id}")
        chunks = await self.chunk_repo.list_by_doc(doc_id)
        parts = []
        for c in chunks:
            head = c.heading or f"片段{c.ordinal}"
            parts.append(f"## {head}\n{c.content}")
        context = "\n\n".join(parts)[:MAX_SECTION_CONTEXT_CHARS]
        return doc.name, context

    # ============ 章节摘要 ============

    async def summarize_sections(self, doc_id: int) -> list[dict]:
        name, context = await self._doc_context(doc_id)
        provider = await self._get_provider()
        prompt = (
            f"为文档《{name}》生成章节摘要。只输出 JSON 数组，每项形如 "
            '{"heading":"章节标题","summary":"2-3句摘要"}。'
            f"\n\n文档内容：\n{context}"
        )
        try:
            raw = await provider.chat(
                [
                    {"role": "system", "content": "你只输出合法 JSON 数组，不要额外文字。"},
                    {"role": "user", "content": prompt},
                ]
            )
        except ProviderError as e:
            logger.warning("summarize_sections failed", error=str(e))
            return []
        items = parse_json_array(raw)
        return [
            {"heading": str(i.get("heading", "")), "summary": str(i.get("summary", ""))}
            for i in items
            if isinstance(i, dict) and i.get("heading")
        ]

    # ============ 术语表 ============

    async def generate_glossary(self, doc_id: int) -> list[dict]:
        name, context = await self._doc_context(doc_id)
        provider = await self._get_provider()
        prompt = (
            f"从文档《{name}》中提取关键术语表。只输出 JSON 数组，每项形如 "
            '{"term":"术语","definition":"简明释义"}。提取 5-15 项。'
            f"\n\n文档内容：\n{context}"
        )
        try:
            raw = await provider.chat(
                [
                    {"role": "system", "content": "你只输出合法 JSON 数组，不要额外文字。"},
                    {"role": "user", "content": prompt},
                ]
            )
        except ProviderError as e:
            logger.warning("generate_glossary failed", error=str(e))
            return []
        items = parse_json_array(raw)
        return [
            {"term": str(i.get("term", "")), "definition": str(i.get("definition", ""))}
            for i in items
            if isinstance(i, dict) and i.get("term")
        ]

    # ============ 多文档对比 ============

    async def compare_documents(self, doc_ids: list[int]) -> dict:
        if len(doc_ids) < 2:
            raise ValueError("对比至少需要 2 个文档")
        if len(doc_ids) > MAX_COMPARE_DOCS:
            raise ValueError(f"对比上限 {MAX_COMPARE_DOCS} 个文档")
        provider = await self._get_provider()
        # 逐文档取上下文
        sections: list[str] = []
        names: list[str] = []
        for did in doc_ids:
            name, ctx = await self._doc_context(did)
            names.append(name)
            sections.append(f"### 文档：{name}\n{ctx[:3000]}")
        joined = "\n\n".join(sections)
        prompt = (
            "对比以下多个文档，输出 JSON 对象：\n"
            '{"common":["共同点1",...],'
            '"differences":[{"doc":"文档名","point":"差异点"}],'
            '"conflicts":["冲突点1",...],'
            '"reading_order":["先读A","再读B"]}。'
            f"\n\n待对比文档：{', '.join(names)}\n\n{joined}"
        )
        try:
            raw = await provider.chat(
                [
                    {"role": "system", "content": "你只输出合法 JSON 对象，不要额外文字。"},
                    {"role": "user", "content": prompt},
                ]
            )
        except ProviderError as e:
            logger.warning("compare_documents failed", error=str(e))
            return {"common": [], "differences": [], "conflicts": [], "reading_order": []}
        obj = parse_json_object(raw) or {}
        return {
            "doc_names": names,
            "common": [str(x) for x in (obj.get("common") or []) if isinstance(x, str)],
            "differences": [
                {"doc": str(d.get("doc", "")), "point": str(d.get("point", ""))}
                for d in (obj.get("differences") or [])
                if isinstance(d, dict)
            ],
            "conflicts": [str(x) for x in (obj.get("conflicts") or [])],
            "reading_order": [str(x) for x in (obj.get("reading_order") or [])],
        }

    # ============ Markdown 导出 ============

    async def export_markdown(
        self, *, content: str, filename: str, target_dir: str
    ) -> dict:
        """把生成内容导出为 Markdown 到授权目录。

        - target_dir 必须在 trusted_paths 中（assert_trusted）。
        - filename 不含路径与扩展名；自动加 .md 并避免覆盖已有文件。
        - 返回 {path, size_bytes}。
        """
        if not content:
            raise ValueError("content 不能为空")
        if len(content.encode("utf-8")) > MAX_EXPORT_BYTES:
            raise ValueError(f"内容过大，上限 {MAX_EXPORT_BYTES} 字节")
        trusted = await TrustedPathRepository(self.db).all_paths()
        assert_trusted(target_dir, trusted)
        # filename 清洗：仅保留文件名部分，去扩展名
        safe_name = Path(filename).name
        safe_name = safe_name.rsplit(".", 1)[0] if "." in safe_name else safe_name
        if not safe_name:
            safe_name = "export"
        target = Path(target_dir).resolve()
        out = target / f"{safe_name}.md"
        # 避免覆盖：若存在则加序号
        idx = 1
        while out.exists():
            out = target / f"{safe_name}_{idx}.md"
            idx += 1
        data = content.encode("utf-8")
        await asyncio.to_thread(out.write_bytes, data)
        logger.info("exported markdown", path=str(out), bytes=len(data))
        return {"path": str(out), "size_bytes": len(data)}

    # ============ 生成笔记入库 ============

    async def import_note_to_kb(self, *, title: str, content: str) -> dict:
        """把生成的 Markdown 内容作为新文档导入知识库。

        创建 Document（doc_type=markdown）→ 写上传文件 → 后台导入。
        """
        from ..workers.importer import import_document

        if not content:
            raise ValueError("content 不能为空")
        safe_title = (title or "note").strip()
        doc = await self.docs.create(
            name=f"{safe_title}.md",
            mime_type="text/markdown",
            size_bytes=len(content.encode("utf-8")),
            embedding_model=settings.embed_model,
            doc_type="markdown",
        )
        upload_dir = Path("./data/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = upload_dir / f"{doc.id}.md"
        await asyncio.to_thread(upload_path.write_bytes, content.encode("utf-8"))
        asyncio.create_task(import_document(doc.id, str(upload_path)))
        return {"doc_id": doc.id, "status": "imported", "name": doc.name}
