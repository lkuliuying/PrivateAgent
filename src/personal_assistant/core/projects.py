"""项目工作区服务：授权、扫描、目录树、文件/内容搜索。

路径安全：所有按 rel_path 访问文件的入口都经 resolve_within 断言解析后仍在项目根下，
防止 ``..`` 越界。项目授权时同步把 root_path 写入 trusted_paths，复用既有越界防护。

M1 只读：不写项目文件、不跑写命令。git status/diff 见 core/code_tools.py。
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_setup import get_logger
from .models import Project, ProjectFile
from .permissions import PermissionError_
from .repo_projects import ProjectFileRepository, ProjectRepository
from .repo_tools import TrustedPathRepository
from .timeutil import utcnow

logger = get_logger(__name__)

# 默认忽略目录（docs/phase3-requirements.md §4.1）
IGNORED_DIRS: set[str] = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    ".next",
    ".nuxt",
    ".cache",
}

# 扫描文件数上限：超大项目截断，避免阻塞与内存膨胀
SCAN_MAX_FILES = 10000
# 单文件大小上限：超过则仍索引元数据但标记不参与内容搜索
MAX_CONTENT_FILE_BYTES = 5 * 1024 * 1024  # 5MB
# grep 时单文件读取上限
MAX_GREP_FILE_BYTES = 2 * 1024 * 1024  # 2MB
GREP_MAX_FILES = 3000
GREP_MAX_RESULTS = 50

# 扩展名 → 语言
EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".vue": "Vue", ".svelte": "Svelte",
    ".rs": "Rust", ".go": "Go",
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".cc": "C++", ".cxx": "C++",
    ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".less": "Less",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML", ".xml": "XML",
    ".md": "Markdown", ".markdown": "Markdown", ".rst": "reStructuredText",
    ".sql": "SQL", ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell",
    ".bat": "Batch", ".cmd": "Batch",
    ".dockerfile": "Dockerfile",
}


class ProjectNotFound(LookupError):
    """项目不存在。"""


def language_for_ext(ext: str) -> str | None:
    return EXT_TO_LANGUAGE.get(ext.lower())


def _detect_is_signature(path: Path, head: bytes) -> bool:
    """粗略二进制检测：首 4KB 含 NUL 字节视为二进制。"""
    return b"\x00" in head[:4096]


def resolve_within(root: str, rel_path: str) -> Path:
    """把 rel_path 解析到 root 下，断言不越界。

    拒绝绝对路径与 ``..`` 逃逸。resolve 后必须位于 root 之内。
    """
    if not rel_path:
        raise PermissionError_("rel_path 不能为空")
    if PurePosixPath(rel_path).is_absolute() or rel_path.startswith("/"):
        raise PermissionError_(f"rel_path 必须为相对路径: {rel_path}")
    root_p = Path(root).resolve()
    target = (root_p / rel_path).resolve()
    try:
        target.relative_to(root_p)
    except ValueError as e:
        raise PermissionError_(f"路径越界: {rel_path}") from e
    return target


def _infer_project(root: Path) -> tuple[str | None, str | None]:
    """根据根目录清单文件推断 (language, framework)。"""
    if (root / "package.json").exists():
        lang = "TypeScript" if (root / "tsconfig.json").exists() else "JavaScript"
        framework = _infer_js_framework(root / "package.json")
        return lang, framework
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists() or (
        root / "requirements.txt"
    ).exists():
        return "Python", _infer_py_framework(root)
    if (root / "Cargo.toml").exists():
        return "Rust", None
    if (root / "go.mod").exists():
        return "Go", None
    if (root / "pom.xml").exists() or (root / "build.gradle").exists() or (
        root / "build.gradle.kts"
    ).exists():
        return "Java", None
    if (root / "composer.json").exists():
        return "PHP", None
    return None, None


def _infer_js_framework(pkg_path: Path) -> str | None:
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    if "vue" in deps:
        return "Vue"
    if "react" in deps:
        return "React"
    if "next" in deps:
        return "Next.js"
    if "nuxt" in deps:
        return "Nuxt"
    if "svelte" in deps:
        return "Svelte"
    if "@angular/core" in deps:
        return "Angular"
    return None


def _infer_py_framework(root: Path) -> str | None:
    """粗略识别 Python 框架：读 pyproject/requirements 里的依赖名。"""
    candidates = [root / "pyproject.toml", root / "requirements.txt"]
    blob = ""
    for p in candidates:
        if p.exists():
            try:
                blob += p.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                pass
    if "fastapi" in blob:
        return "FastAPI"
    if "django" in blob:
        return "Django"
    if "flask" in blob:
        return "Flask"
    return None


def walk_project_files(root: Path) -> list[dict]:
    """遍历项目目录，返回文件索引条目（应用忽略规则与上限）。

    返回 [{rel_path, language, size_bytes, content_hash, mtime, is_binary}, ...]。
    rel_path 用 POSIX 分隔符（与 resolve_within 的 PurePosixPath 一致）。
    content_hash 不计算（M1 用 replace_all 全量重建；增量哈希留后续优化）。
    """
    root = root.resolve()
    out: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # 忽略目录：任一父段命中 IGNORED_DIRS 即跳过
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if any(p in IGNORED_DIRS for p in parts[:-1]):
            continue
        if len(out) >= SCAN_MAX_FILES:
            break
        rel_path = PurePosixPath(*parts).as_posix()
        # 跳过符号链接：防止索引/读取项目根外文件（链接目标可能越界）
        if path.is_symlink():
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        ext = path.suffix.lower()
        is_binary = False
        # 仅对小文件做二进制探测（大文件按扩展名/默认非二进制）
        if st.st_size <= 65536 and ext not in {".txt", ".md", ".markdown"}:
            try:
                head = path.read_bytes()[:8192]
                is_binary = _detect_is_signature(path, head)
            except OSError:
                is_binary = True
        elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
                     ".zip", ".gz", ".tar", ".class", ".so", ".dll", ".exe", ".wasm"}:
            is_binary = True
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).replace(tzinfo=None)
        out.append(
            {
                "rel_path": rel_path,
                "language": language_for_ext(ext),
                "size_bytes": st.st_size,
                "content_hash": None,
                "mtime": mtime,
                "is_binary": is_binary,
                "indexed_at": utcnow(),
            }
        )
    return out


def build_tree(files: list[ProjectFile]) -> dict:
    """由 project_files 构建嵌套目录树。

    返回 {dirs: [...], files: [...]}，dirs 递归含 {name, path, dirs, files}。
    """
    root_node: dict = {"dirs": [], "files": []}
    # 用 dict 暂存目录子节点便于查找
    dir_index: dict[str, dict] = {}

    def _ensure_dir(path: str) -> dict:
        if path in dir_index:
            return dir_index[path]
        parts = path.split("/")
        node = {"name": parts[-1], "path": path, "dirs": [], "files": []}
        dir_index[path] = node
        if len(parts) == 1:
            root_node["dirs"].append(node)
        else:
            parent_path = "/".join(parts[:-1])
            parent = _ensure_dir(parent_path)
            parent["dirs"].append(node)
        return node

    for f in files:
        parts = f.rel_path.split("/")
        if len(parts) > 1:
            dir_path = "/".join(parts[:-1])
            node = _ensure_dir(dir_path)
        else:
            node = root_node
        node["files"].append(
            {
                "name": parts[-1],
                "path": f.rel_path,
                "language": f.language,
                "size_bytes": f.size_bytes,
                "is_binary": f.is_binary,
            }
        )
    # 目录与文件按名排序，保证稳定
    def _sort(node: dict) -> None:
        node["dirs"].sort(key=lambda d: d["name"])
        node["files"].sort(key=lambda f: f["name"])
        for d in node["dirs"]:
            _sort(d)

    _sort(root_node)
    return root_node


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProjectRepository(db)
        self.file_repo = ProjectFileRepository(db)

    async def authorize(self, *, name: str, root_path: str) -> Project:
        """授权项目目录：校验 → 去重 → 推断语言 → 建 project → 同步 trusted_paths。"""
        p = Path(root_path).expanduser()
        if not p.is_absolute():
            raise ValueError("root_path 必须为绝对路径")
        if not p.exists() or not p.is_dir():
            raise ValueError("项目目录不存在或不是目录")
        root_str = str(p.resolve())
        existing = await self.repo.get_by_path(root_str)
        if existing:
            # 已授权：确保 trusted_paths 也有记录（幂等）
            await TrustedPathRepository(self.db).authorize(root_str, "directory")
            return existing
        language, framework = await asyncio.to_thread(_infer_project, p.resolve())
        project = await self.repo.create(
            name=name, root_path=root_str, language=language, framework=framework
        )
        await TrustedPathRepository(self.db).authorize(root_str, "directory")
        logger.info("project authorized", project_id=project.id, root=root_str, language=language)
        return project

    async def get(self, project_id: int) -> Project:
        project = await self.repo.get(project_id)
        if project is None:
            raise ProjectNotFound(f"项目不存在: {project_id}")
        return project

    async def list(self) -> list[Project]:
        return await self.repo.list()

    async def tree(self, project_id: int) -> dict:
        project = await self.get(project_id)
        files = await self.file_repo.list_by_project(project.id)
        return build_tree(files)

    async def files(
        self,
        project_id: int,
        *,
        ext: str | None = None,
        language: str | None = None,
        limit: int = 500,
    ) -> list[ProjectFile]:
        project = await self.get(project_id)
        files = await self.file_repo.list_by_project(project.id)
        out = files
        if ext:
            ext_l = ext.lower()
            out = [f for f in out if f.rel_path.endswith(ext_l) or Path(f.rel_path).suffix.lower() == ext_l]
        if language:
            out = [f for f in out if (f.language or "") == language]
        return out[:limit]

    async def file_stats(self, project_id: int) -> dict:
        """项目文件统计：总数、按语言计数、二进制数。"""
        files = await self.file_repo.list_by_project(project_id)
        by_lang: dict[str, int] = {}
        binary = 0
        for f in files:
            if f.is_binary:
                binary += 1
            lang = f.language or "其他"
            by_lang[lang] = by_lang.get(lang, 0) + 1
        return {"total": len(files), "binary": binary, "by_language": by_lang}

    async def search_name(self, project_id: int, query: str, limit: int = 50) -> list[ProjectFile]:
        """按文件名/相对路径搜索。"""
        await self.get(project_id)
        return await self.file_repo.search_by_name(project_id, query, limit=limit)

    async def search_content(
        self,
        project_id: int,
        pattern: str,
        stop_event: "threading.Event | None" = None,
    ) -> dict:
        """在已索引文本文件中 grep，返回 path/line/上下文。

        R3：``stop_event`` 让 to_thread 的扫描循环在取消时提前退让
        （线程不可强杀，迟到结果由调用方丢弃）。
        """
        project = await self.get(project_id)
        files = await self.file_repo.list_by_project(project.id)
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"无效正则: {e}")

        root = project.root_path

        def _grep() -> dict:
            hits: list[dict] = []
            scanned = 0
            for f in files:
                if stop_event is not None and stop_event.is_set():
                    break
                if f.is_binary:
                    continue
                if f.size_bytes and f.size_bytes > MAX_GREP_FILE_BYTES:
                    continue
                if scanned >= GREP_MAX_FILES:
                    break
                scanned += 1
                # 经 resolve_within 二次断言：rel_path 解析后仍在项目根下（防符号链接/越界）
                try:
                    full = resolve_within(root, f.rel_path)
                except PermissionError_:
                    continue
                try:
                    text = full.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    if stop_event is not None and stop_event.is_set():
                        break
                    if regex.search(line):
                        ctx = line.strip()
                        if len(ctx) > 300:
                            ctx = ctx[:300] + "…"
                        hits.append(
                            {
                                "rel_path": f.rel_path,
                                "line": lineno,
                                "context": ctx,
                                "language": f.language,
                            }
                        )
                        if len(hits) >= GREP_MAX_RESULTS:
                            return {"results": hits, "count": len(hits), "truncated": True}
            return {"results": hits, "count": len(hits), "truncated": False}

        return await asyncio.to_thread(_grep)
