"""v0.6.0 RunArtifact 服务：run 产物引用持久化（C0 契约 §4.2/§8）。

只冻结产物引用：kind/title/rel_path/content_sha256/metadata_json，
不新增任意文件下载或外部上传能力。写入后发 ``artifact.created``
durable 事件（独立 session，失败仅记日志；快照纠偏兜底）。
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.contracts import AgentEventType
from ..logging_setup import get_logger
from .db import async_session_factory
from .models import AgentRunArtifact

logger = get_logger(__name__)

ARTIFACT_KINDS = frozenset(
    {"diff", "file", "command_output", "test_report", "summary"}
)
MAX_TITLE = 512
MAX_REL_PATH = 2048
MAX_METADATA_BYTES = 32 * 1024


class ArtifactValidationError(Exception):
    """artifact 输入非法（422 artifact_invalid）。"""


class RunArtifactService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _validate_rel_path(rel_path: str | None) -> None:
        if rel_path is None:
            return
        if not rel_path or len(rel_path) > MAX_REL_PATH:
            raise ArtifactValidationError(
                f"rel_path must be 1..{MAX_REL_PATH} characters"
            )
        # 只允许 workspace 相对路径：禁止绝对路径、盘符、反斜杠和上级引用
        if (
            rel_path.startswith("/")
            or rel_path.startswith("\\")
            or ":" in rel_path.split("/", 1)[0]
            or "\\" in rel_path
            or any(
                part in {"..", "."} or not part
                for part in rel_path.split("/")
            )
        ):
            raise ArtifactValidationError(
                "rel_path must be a normalized workspace-relative path"
            )

    @staticmethod
    def _validate_metadata(metadata: dict | None) -> dict | None:
        if metadata is None:
            return None
        if not isinstance(metadata, dict):
            raise ArtifactValidationError("metadata must be a JSON object")
        try:
            encoded = __import__("json").dumps(
                metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ArtifactValidationError(
                "metadata must be JSON-serializable"
            ) from exc
        if len(encoded) > MAX_METADATA_BYTES:
            raise ArtifactValidationError(
                f"metadata must be at most {MAX_METADATA_BYTES} bytes"
            )
        return metadata

    async def create_artifact(
        self,
        *,
        run_id: str,
        kind: str,
        title: str,
        rel_path: str | None = None,
        step_id: str | None = None,
        content_sha256: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """创建产物引用并写 artifact.created durable 事件。"""
        if kind not in ARTIFACT_KINDS:
            raise ArtifactValidationError(
                f"kind must be one of {sorted(ARTIFACT_KINDS)}"
            )
        if not isinstance(title, str) or not 1 <= len(title) <= MAX_TITLE:
            raise ArtifactValidationError(
                f"title must be 1..{MAX_TITLE} characters"
            )
        if step_id is not None and (
            not isinstance(step_id, str) or not 1 <= len(step_id) <= 36
        ):
            raise ArtifactValidationError("step_id must be at most 36 characters")
        if content_sha256 is not None and (
            not isinstance(content_sha256, str) or len(content_sha256) != 64
        ):
            raise ArtifactValidationError("content_sha256 must be a 64-char hex digest")
        self._validate_rel_path(rel_path)
        validated_metadata = self._validate_metadata(metadata)

        record = AgentRunArtifact(
            id=str(uuid4()),
            run_id=run_id,
            step_id=step_id,
            kind=kind,
            title=title,
            rel_path=rel_path,
            content_sha256=content_sha256,
            metadata_json=validated_metadata,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        await self._emit_event(
            run_id,
            AgentEventType.ARTIFACT_CREATED,
            {
                "artifact_id": record.id,
                "kind": record.kind,
                "title": record.title,
                "step_id": record.step_id,
            },
        )
        return self._to_dict(record)

    async def list_artifacts(self, run_id: str) -> list[dict]:
        stmt = (
            select(AgentRunArtifact)
            .where(AgentRunArtifact.run_id == run_id)
            .order_by(AgentRunArtifact.created_at, AgentRunArtifact.id)
        )
        result = await self.db.execute(stmt)
        return [self._to_dict(record) for record in result.scalars().all()]

    async def _emit_event(
        self, run_id: str, event_type: AgentEventType, payload: dict
    ) -> None:
        """写 durable artifact 事件（独立 session，失败仅记日志）。"""
        try:
            from ..agents.contracts import AgentEvent
            from ..agents.repository import AgentRunRepository

            async with async_session_factory() as session:
                run_repo = AgentRunRepository(session)
                run = await run_repo.get_run(run_id)
                if run is None:
                    return
                await run_repo.record_event(
                    AgentEvent(
                        run_id=run_id,
                        sequence=run.last_event_sequence + 1,
                        type=event_type,
                        payload=payload,
                    )
                )
        except Exception:
            logger.warning(
                "artifact durable event emit failed",
                run_id=run_id,
                event_type=event_type.value,
                exc_info=True,
            )

    @staticmethod
    def _to_dict(record: AgentRunArtifact) -> dict:
        return {
            "id": record.id,
            "run_id": record.run_id,
            "step_id": record.step_id,
            "kind": record.kind,
            "title": record.title,
            "rel_path": record.rel_path,
            "content_sha256": record.content_sha256,
            "metadata": record.metadata_json,
            "created_at": record.created_at.isoformat()
            if record.created_at is not None
            else None,
        }
