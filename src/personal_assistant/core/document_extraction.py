"""文档结构化抽取服务（第四阶段 M3）。

从单文档或文档集合抽取结构化信息（术语/行动项/关键观点/表格摘要/代码片段），
并按模板生成 Markdown 报告。复用 learning.py 的 JSON 解析助手与 ExportService 的
provider 构造模式；上下文为每段标注来源（文档 id + 片段 ordinal），抽取结果保留
source_refs_json 以支持溯源回 doc/chunk。

OCR 仅预留接口（M3 不引入引擎依赖），返回明确 unavailable 状态，不改动文档。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .learning import parse_json_array
from .provider import OllamaProvider, ProviderError
from .repo import DocChunkRepository, DocumentRepository
from .repo_documents import DocumentCollectionRepository, DocumentExtractionRepository
from .settings import SettingsService

logger = get_logger(__name__)

MAX_CONTEXT_PER_DOC = 6000
MAX_TOTAL_CONTEXT = 12000

# 抽取类型 → (说明, JSON 项 schema 提示)
EXTRACTION_KINDS: dict[str, str] = {
    "terms": "关键术语表，每项 {term, definition, source}",
    "actions": "可执行的行动项，每项 {action, priority(高/中/低), source}",
    "claims": "关键观点/论断，每项 {claim, support, source}",
    "table_summary": "表格/列表摘要，每项 {title, summary, source}",
    "code": "代码片段，每项 {language, description, code, source}",
}

# 模板报告类型 → 用途说明
TEMPLATE_KINDS: dict[str, str] = {
    "study_note": "学习笔记：梳理知识点、要点、疑问",
    "tech_summary": "技术文档摘要：架构、接口、关键流程",
    "paper_reading": "论文阅读：研究问题、方法、结论、局限",
    "project_materials": "项目资料整理：背景、模块、依赖、注意事项",
    "meeting_minutes": "会议纪要：议题、讨论要点、决议、待办与负责人",
}


class ExtractionNotFound(LookupError):
    """文档/集合不存在。"""


class DocumentExtractionService:
    def __init__(self, db: AsyncSession, provider: OllamaProvider | None = None) -> None:
        self.db = db
        self._provider = provider
        self.docs = DocumentRepository(db)
        self.chunk_repo = DocChunkRepository(db)
        self.collections = DocumentCollectionRepository(db)
        self.extractions = DocumentExtractionRepository(db)

    async def _get_provider(self) -> OllamaProvider:
        if self._provider is not None:
            return self._provider
        s = await SettingsService(self.db).get_all()
        return OllamaProvider(
            llm_model=s["llm_model"],
            temperature=float(s["llm_temperature"]),
            context_length=int(s["llm_context_length"]),
        )

    # ============ 上下文收集（带来源标注）============

    async def _resolve_doc_ids(
        self, doc_id: int | None, collection_id: int | None
    ) -> list[int]:
        """从 doc_id 或 collection_id 解析目标文档 id 列表。"""
        if doc_id is not None:
            doc = await self.docs.get(doc_id)
            if doc is None:
                raise ExtractionNotFound(f"文档不存在: {doc_id}")
            return [doc_id]
        if collection_id is not None:
            coll = await self.collections.get(collection_id)
            if coll is None:
                raise ExtractionNotFound(f"文档集合不存在: {collection_id}")
            items = await self.collections.list_items(collection_id)
            return [it.doc_id for it in items]
        raise ValueError("需指定 doc_id 或 collection_id")

    async def _gather_context(
        self, doc_ids: list[int]
    ) -> tuple[str, list[dict]]:
        """拼接带来源标注的切片上下文，返回 (context, source_refs)。

        source_refs 每项 {doc_id, doc_name, chunk_id, chunk_ordinal, heading}，
        仅记录内容真正进入上下文的切片（受 per-doc / total 上限约束），保证溯源准确，
        不记录被截断掉的切片。无切片的文档整体跳过，避免 join 产生空段。
        """
        parts: list[str] = []
        refs: list[dict] = []
        total = 0
        for did in doc_ids:
            if total >= MAX_TOTAL_CONTEXT:
                break
            doc = await self.docs.get(did)
            if doc is None:
                continue  # 容忍悬空软引用
            chunks = await self.chunk_repo.list_by_doc(did)
            doc_parts: list[str] = []
            doc_len = 0
            for c in chunks:
                head = c.heading or f"片段{c.ordinal}"
                label = f"【文档《{doc.name}》(id={did}) 片段{c.ordinal}】"
                piece = f"{label}{head}\n{c.content}"
                if doc_len + len(piece) > MAX_CONTEXT_PER_DOC:
                    break  # 单文档上限：后续切片不入上下文，也不记 source_refs
                if total + doc_len + len(piece) > MAX_TOTAL_CONTEXT:
                    break  # 总量上限
                doc_parts.append(piece)
                refs.append(
                    {
                        "doc_id": did,
                        "doc_name": doc.name,
                        "chunk_id": c.id,
                        "chunk_ordinal": c.ordinal,
                        "heading": head,
                    }
                )
                doc_len += len(piece)
            if doc_parts:  # 跳过无切片/被全截断的文档，避免 join 产生空段
                parts.append("\n\n".join(doc_parts))
                total += doc_len
        context = "\n\n---\n\n".join(parts)[:MAX_TOTAL_CONTEXT]
        return context, refs

    # ============ 结构化抽取 ============

    async def extract(
        self,
        kind: str,
        *,
        doc_id: int | None = None,
        collection_id: int | None = None,
    ) -> object:
        """对文档/集合执行结构化抽取，落库并返回 DocumentExtraction。"""
        if kind not in EXTRACTION_KINDS:
            raise ValueError(f"未知抽取类型: {kind}（应为 {list(EXTRACTION_KINDS)}）")
        doc_ids = await self._resolve_doc_ids(doc_id, collection_id)
        if not doc_ids:
            raise ValueError("目标无文档，无法抽取")
        context, refs = await self._gather_context(doc_ids)
        if not context or not refs:
            raise ValueError("目标文档无切片内容，请先完成索引")
        provider = await self._get_provider()
        schema_hint = EXTRACTION_KINDS[kind]
        prompt = (
            f"从下方资料中抽取{schema_hint}。source 字段填写来源标注（如「片段3」或"
            f"「文档《名》片段3」）。只输出 JSON 数组，不要额外文字。\n\n资料：\n{context}"
        )
        try:
            raw = await provider.chat(
                [
                    {"role": "system", "content": "你只输出合法 JSON 数组，不要额外文字。"},
                    {"role": "user", "content": prompt},
                ]
            )
        except ProviderError as e:
            logger.warning("extract failed", kind=kind, error=str(e))
            items: list = []
        else:
            items = parse_json_array(raw)

        content_md = self._render_extraction_md(kind, items)
        return await self.extractions.create(
            doc_id=doc_id,
            collection_id=collection_id,
            kind=kind,
            content_json={"kind": kind, "items": items},
            content_md=content_md,
            source_refs_json=refs,
        )

    @staticmethod
    def _render_extraction_md(kind: str, items: list) -> str:
        """把抽取项渲染为可读 Markdown。"""
        if not items:
            return f"## {kind}\n\n（未抽取到内容）"
        lines = [f"## {kind}", ""]
        for i, it in enumerate(items, 1):
            if not isinstance(it, dict):
                continue
            title = (
                it.get("term")
                or it.get("action")
                or it.get("claim")
                or it.get("title")
                or it.get("description")
                or f"项{i}"
            )
            lines.append(f"### {i}. {title}")
            for k, v in it.items():
                if k in ("term", "action", "claim", "title", "description"):
                    continue
                lines.append(f"- **{k}**: {v}")
            lines.append("")
        return "\n".join(lines)

    # ============ 模板报告 ============

    async def generate_template_report(
        self,
        template: str,
        *,
        doc_ids: list[int] | None = None,
        collection_id: int | None = None,
    ) -> dict:
        """按模板生成 Markdown 报告，落库 kind=template_report，返回 {report_md, extraction}。"""
        if template not in TEMPLATE_KINDS:
            raise ValueError(
                f"未知模板: {template}（应为 {list(TEMPLATE_KINDS)}）"
            )
        if collection_id is not None:
            doc_ids = await self._resolve_doc_ids(None, collection_id)
        elif not doc_ids:
            raise ValueError("需指定 doc_ids 或 collection_id")
        else:
            # 显式 doc_ids 校验存在性（与 extract 的 doc_id 路径一致），缺失→404；
            # collection 路径仍容忍悬空软引用（_gather_context 跳过 None）。
            for did in doc_ids:
                if await self.docs.get(did) is None:
                    raise ExtractionNotFound(f"文档不存在: {did}")
        context, refs = await self._gather_context(doc_ids)
        if not context or not refs:
            raise ValueError("目标文档无切片内容，请先完成索引")
        provider = await self._get_provider()
        purpose = TEMPLATE_KINDS[template]
        prompt = (
            f"基于下方资料，按「{template}」模板生成一份结构清晰的 Markdown 报告。"
            f"用途：{purpose}。报告应有合适的小标题与要点，并在引用处标注来源片段。"
            f"\n\n资料：\n{context}"
        )
        try:
            report_md = await provider.chat(
                [
                    {"role": "system", "content": "你输出 Markdown 格式的报告。"},
                    {"role": "user", "content": prompt},
                ]
            )
        except ProviderError as e:
            logger.warning("template_report failed", template=template, error=str(e))
            report_md = f"# {template}\n\n（LLM 生成失败：{e}）"
        extraction = await self.extractions.create(
            collection_id=collection_id,
            kind="template_report",
            content_json={"template": template, "doc_ids": doc_ids},
            content_md=report_md,
            source_refs_json=refs,
        )
        return {"report_md": report_md, "extraction": extraction}

    # ============ OCR（M3 仅预留接口）============

    async def ocr_document(self, doc_id: int) -> dict:
        """OCR 处理入口（M3 预留）：未引入引擎，返回 unavailable，不改文档状态。"""
        doc = await self.docs.get(doc_id)
        if doc is None:
            raise ExtractionNotFound(f"文档不存在: {doc_id}")
        return {
            "doc_id": doc_id,
            "status": "unavailable",
            "message": "OCR 引擎未配置（M3 仅预留接口，引擎可选安装）。",
        }
