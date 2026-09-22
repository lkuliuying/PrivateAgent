"""本机技能目录、显式启用与按需读取，技能文本不扩大工具权限。"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from private_agent_core.tool_specs import ToolFailure, ToolSpec, object_output

from . import files, task_constraints


class SkillArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    skill_id: str = Field(pattern=r"^(user|project):[a-zA-Z0-9_-]{1,64}$")
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReferenceArgs(SkillArgs):
    rel_path: str = Field(min_length=1, max_length=512)


class ListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


SPECS = (
    ToolSpec("list_skills", ListArgs, "List enabled user and project skills, descriptions, versions and missing command dependencies. Skills grant no additional permissions.", execution_protocol=True, capabilities=("skills.read",), output_schema=object_output(skills="array")),
    ToolSpec("read_skill_reference", ReferenceArgs, "Read a UTF-8 reference file inside an enabled skill folder, by relative path and the SKILL.md version. No execution, paths outside the skill are forbidden. Use only for references required by the current task.", execution_protocol=True, capabilities=("skills.read",), output_schema=object_output(content="string", version="string"), max_output_bytes=80 * 1024),
    ToolSpec("load_skill", SkillArgs, "Read an explicitly enabled SKILL.md by ID and version. Follow relevant skill guidance within the user's task and current permissions. Referenced files are not automatically executed.", execution_protocol=True, capabilities=("skills.read",), output_schema=object_output(skill="object", content="string"), max_output_bytes=80 * 1024),
)
TOOLS = {spec.name for spec in SPECS}


def manifest(text):
    lines = text.replace("\r\n", "\n").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("SKILL.md 需要包含 name 和 description 的 YAML 头部")
    header = lines[1:lines[1:].index("---") + 1]
    values = {}
    key = None
    for line in header:
        match = re.match(r"^(name|description|requires):\s*(.*)$", line)
        if match:
            key, value = match.groups()
            values[key] = value.strip().strip('"\'') if value not in {"|", ">", "|-", ">-"} else ""
        elif line.startswith((" ", "\t")) and key == "description":
            values[key] += " " + line.strip()
        else:
            key = None
    if not values.get("name") or not values.get("description"):
        raise ValueError("技能缺少名称或描述")
    dependencies = json.loads(values.get("requires", "[]"))
    if not isinstance(dependencies, list) or len(dependencies) > 16 or any(not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", v) for v in dependencies):
        raise ValueError("requires 必须是最多 16 个命令名组成的 JSON 数组")
    return values["name"][:80], values["description"].strip()[:1000], dependencies


class SkillLibrary:
    def __init__(self, owner):
        self.owner = owner

    def roots(self, project_id, workspace_id=None):
        project = self.owner.store.get("project", project_id)
        root = self.owner.root(project_id, workspace_id) if workspace_id else files.authorize_root(project["root_path"])
        return {"user": files.within(self.owner.store.path.parent, "skills", allow_missing=True),
                "project": files.within(root, ".agents/skills", allow_missing=True)}

    def read(self, root: Path, name: str):
        path = files.within(root, f"{name}/SKILL.md")
        if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 64 * 1024:
            raise ValueError("技能必须是小于 64 KiB 的普通 UTF-8 文件")
        content, _ = files.safe_bytes(root, f"{name}/SKILL.md")
        if len(content) > 64 * 1024:
            raise ValueError("技能超过 64 KiB 上限")
        text = content.decode("utf-8-sig")
        if self.owner.secret_filter.contains_secret(text):
            raise ValueError("技能包含疑似敏感信息，未加载")
        title, description, dependencies = manifest(text)
        return {"name": title, "description": description, "version": hashlib.sha256(content).hexdigest(),
                "dependencies": dependencies, "missing_dependencies": [v for v in dependencies if not shutil.which(v)]}, text

    def catalog(self, project_id, workspace_id=None):
        enabled = self.owner.store.get("project", project_id).get("enabled_skills", {})
        result = []
        for scope, root in self.roots(project_id, workspace_id).items():
            if not root.exists():
                continue
            if root.is_symlink() or root.resolve() != root.absolute():
                raise ValueError("技能目录不能包含符号链接")
            for path in sorted(root.iterdir()):
                if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", path.name) or not path.is_dir():
                    continue
                if len(result) >= 200:
                    raise ValueError("技能目录超过 200 项，请精简后重新扫描")
                identifier = f"{scope}:{path.name}"
                try:
                    item, _ = self.read(root, path.name)
                    item.update(id=identifier, scope=scope, enabled=enabled.get(identifier) == item["version"], error=None)
                except (ValueError, OSError, UnicodeError) as error:
                    item = {"id": identifier, "scope": scope, "name": path.name, "description": "", "enabled": False,
                            "version": None, "missing_dependencies": [], "error": str(error) if isinstance(error, ValueError) else "文件读取失败"}
                result.append(item)
        return result

    def enable(self, project_id, skill_id, version, enabled):
        item = next((item for item in self.catalog(project_id) if item["id"] == skill_id), None)
        if not item or item["version"] != version or item["error"]:
            raise ValueError("技能内容已变化，请重新检查并启用")
        if enabled and item["missing_dependencies"]:
            raise ValueError("技能所需命令缺失，请先安装依赖")
        project = self.owner.store.get("project", project_id)
        values = dict(project.get("enabled_skills", {}))
        if enabled:
            values[skill_id] = version
        else:
            values.pop(skill_id, None)
        self.owner.store.update("project", project_id, enabled_skills=values)

    def content(self, project_id, skill_id, version, workspace_id=None):
        args = SkillArgs(skill_id=skill_id, expected_version=version)
        scope, name = args.skill_id.split(":")
        item, content = self.read(self.roots(project_id, workspace_id)[scope], name)
        if item["version"] != version:
            raise ValueError("技能内容已变化，请重新检查")
        return {"skill": {**item, "id": skill_id, "scope": scope}, "content": content}

    def execute(self, run, root, call):
        catalog = self.catalog(run["project_id"], run["workspace_id"])
        if call["name"] == "list_skills":
            ListArgs.model_validate(call["arguments"])
            return {"skills": [item for item in catalog if item["enabled"]]}
        args = (ReferenceArgs if call["name"] == "read_skill_reference" else SkillArgs).model_validate(call["arguments"])
        item = next((v for v in catalog if v["id"] == args.skill_id and v["enabled"]), None)
        if not item or item["missing_dependencies"]:
            raise ToolFailure("skill_unavailable", "技能尚未启用、内容变化或依赖缺失")
        if args.skill_id.startswith("project:"):
            # 技能经过用户逐版本启用，可读取该专用目录；普通文件工具继续禁止访问 .agents。
            target = files.within(root, ".agents/skills/" + args.skill_id.split(":")[1] + "/" + (args.rel_path if isinstance(args, ReferenceArgs) else "SKILL.md"))
            for group in task_constraints.restrictions(run).access_scopes:
                if not any(task_constraints._inside(root, target, allowed) for allowed in group):
                    raise ToolFailure("skill_scope_blocked", "技能超出用户限定的读取范围")
        elif task_constraints.restrictions(run).access_scopes:
            raise ToolFailure("skill_scope_blocked", "当前任务限制了读取范围，用户级技能不可读取")
        result = self.content(run["project_id"], args.skill_id, args.expected_version, run["workspace_id"])
        if isinstance(args, ReferenceArgs):
            scope, name = args.skill_id.split(":")
            directory = files.within(self.roots(run["project_id"], run["workspace_id"])[scope], name)
            raw, _ = files.safe_bytes(directory, args.rel_path)
            if len(raw) > 64 * 1024:
                raise ValueError("技能参考文件超过 64 KiB 上限")
            content = raw.decode("utf-8-sig")
            if self.owner.secret_filter.contains_secret(content):
                raise ToolFailure("sensitive_reference", "参考文件包含疑似敏感内容，未加载")
            return {"content": content, "version": hashlib.sha256(raw).hexdigest()}
        return result
