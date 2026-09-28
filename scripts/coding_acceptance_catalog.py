"""S6 固定任务重建和外置判定；复用已有解释器，不安装依赖。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path

from coding_acceptance_evidence import digest
from coding_acceptance_schema import (
    fingerprint,
    load_external,
    plain_path,
    safe_relative,
)
from coding_task_baseline import materialize
from coding_validation_process import managed_process
from run_coding_validation import ROOT, isolated_environment

CATALOG_SOURCE = ROOT / "tests/coding_acceptance/s6_fixtures.py"


def load_catalog(path: Path | None = None) -> dict:
    if path is not None:
        return load_external(path)
    spec = importlib.util.spec_from_file_location("s6_frozen_fixtures", CATALOG_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.catalog()
    tasks = result["tasks"]
    if len(tasks) != 30 or len({task["id"] for task in tasks}) != 30:
        raise ValueError("S6 必须包含 30 个唯一任务")
    if Counter(task["family"] for task in tasks) != {"python": 10, "vue-typescript": 10, "rust": 10}:
        raise ValueError("S6 项目语言分布不符")
    if Counter(task["category"] for task in tasks) != dict.fromkeys(("bug", "feature", "refactor", "long_context", "recovery", "boundary"), 5):
        raise ValueError("S6 主分类分布不符")
    for family in {task["family"] for task in tasks}:
        if Counter(task["split"] for task in tasks if task["family"] == family) != {"development": 6, "holdout": 4}:
            raise ValueError("S6 开发/保留集划分不符")
    for task in tasks:
        if set(task["editable_files"]) != set(task["reference_files"]) or not set(task["editable_files"]) <= task["files"].keys():
            raise ValueError("可编辑范围与参考文件不符")
        for name in task["files"]:
            safe_relative(name)
    result["catalog_sha256"] = digest(CATALOG_SOURCE)
    result.update(catalog_path=str(CATALOG_SOURCE), catalog_source="builtin_calibration",
                  purpose="public_calibration", isolation={"verified": False, "reason": "public_calibration"})
    for task in tasks:
        task["task_sha256"] = fingerprint(task)
    return result


def preflight(tasks: list[dict]) -> dict:
    requirements = {"python": Path(sys.executable)}
    for name in ("pytest", "httpx", "fastapi", "uvicorn"):
        specification = importlib.util.find_spec(name)
        requirements[name] = Path(specification.origin) if specification and specification.origin else None
    families = {task["family"] for task in tasks}
    if "rust" in families:
        requirements.update({name: Path(path) if (path := shutil.which(name)) else None for name in ("rustc", "cargo")})
    if "vue-typescript" in families:
        requirements["node"] = Path(path) if (path := shutil.which("node")) else None
        requirements["npm"] = Path(path) if (path := shutil.which("npm")) else None
        for name in ("typescript", "vue", "@vue/compiler-sfc", "@vue/server-renderer"):
            requirements[name] = ROOT / "apps/desktop/node_modules" / name / "package.json"
    missing = [name for name, path in requirements.items() if path is None or not path.is_file()]
    rust_config = None
    if "rust" in families:
        try:
            if not rust_toolchain():
                missing.append("rust-toolchain")
            rust_config = windows_rust_config()
        except (OSError, ValueError, subprocess.SubprocessError):
            missing.append("rust-linker-sdk")
    return {"passed": not missing, "missing": missing, "rust_configuration": rust_config, "tools": {name: {"path": str(path), "sha256": digest(path)}
            for name, path in requirements.items() if path and path.is_file()}}


def rust_toolchain() -> Path | None:
    compiler = shutil.which("rustc")
    if not compiler:
        return None
    result = subprocess.run([compiler, "--print", "sysroot"], capture_output=True, timeout=10, check=True)
    directory = Path(result.stdout.decode().strip()) / "bin"
    if not (directory / ("cargo.exe" if os.name == "nt" else "cargo")).is_file():
        raise ValueError("Rust 工具链缺少 cargo，不自动下载")
    return directory


def windows_rust_config() -> str | None:
    if os.name != "nt":
        return None
    import winreg

    # 从安装元数据固定链接器及 SDK 路径，不执行 vcvars、不继承用户 Cargo 配置。
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion") as key:
        programs = Path(winreg.QueryValueEx(key, "ProgramFilesDir (x86)")[0])
    locator = programs / "Microsoft Visual Studio/Installer/vswhere.exe"
    result = subprocess.run([str(locator), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                             "-property", "installationPath"], capture_output=True, timeout=10, check=True)
    installation = Path(result.stdout.decode("utf-8").strip())
    version = (installation / "VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt").read_text().strip()
    msvc = installation / "VC/Tools/MSVC" / version
    linker = msvc / "bin/Hostx64/x64/link.exe"
    sdk = programs / "Windows Kits/10/Lib"
    versions = sorted(path for path in sdk.iterdir() if (path / "um/x64/kernel32.lib").is_file() and (path / "ucrt/x64/ucrt.lib").is_file())
    if not linker.is_file() or not versions or not (msvc / "lib/x64/libcmt.lib").is_file():
        raise ValueError("缺少 MSVC x64 链接器或 Windows SDK；不自动安装")
    libraries = [msvc / "lib/x64", versions[-1] / "um/x64", versions[-1] / "ucrt/x64"]
    return '[target.x86_64-pc-windows-msvc]\nlinker = ' + json.dumps(str(linker)) + '\nrustflags = ' + json.dumps(["-Lnative=" + str(path) for path in libraries]) + '\n'


def snapshot(directory: Path) -> dict[str, str]:
    plain_path(directory)
    result = {}
    size = 0
    generated_links = {}
    for path in directory.rglob("*"):
        relative = path.relative_to(directory).as_posix()
        # 忽略构建产物前先检查链接，防止把别名藏在 target 或 .git 中。
        status = path.lstat()
        if path.is_symlink() or getattr(status, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("任务工作区包含链接或越界文件")
        if any(part in {".git", "__pycache__", "target"} for part in path.relative_to(directory).parts):
            if stat.S_ISREG(status.st_mode) and status.st_nlink > 1:
                # Cargo 的内部产物会硬链接复用；只有全部链接都在本工作区生成目录内才接受。
                key = (status.st_dev, status.st_ino)
                count, expected = generated_links.get(key, (0, status.st_nlink))
                if expected != status.st_nlink:
                    raise ValueError("构建产物的链接数在快照期间发生变化")
                generated_links[key] = (count + 1, expected)
            continue
        if stat.S_ISREG(status.st_mode) and status.st_nlink != 1:
            raise ValueError("任务源码包含硬链接")
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("任务工作区包含链接或越界文件")
        if path.is_file():
            size += path.stat().st_size
            if size > 8 * 1024 * 1024 or len(result) >= 1000:
                raise ValueError("任务源码超过 1000 文件/8 MiB 配额")
            result[relative] = digest(path)
    if any(count != expected for count, expected in generated_links.values()):
        raise ValueError("构建产物包含指向工作区外的硬链接")
    return result


def storage_usage(directory: Path, *, max_bytes=256 * 1024 * 1024, max_files=20000) -> int:
    pending, count, size = [directory], 0, 0
    cache_alias = directory / "home/AppData/Local/Microsoft/Windows/INetCache/Content.IE5"

    def known_cache_alias(path, status):
        # Windows 自动建立此兼容别名；真实 IE 目录仍正常计量，不跟随别名重复遍历。
        return (path == cache_alias and getattr(status, "st_reparse_tag", 0) == stat.IO_REPARSE_TAG_MOUNT_POINT
                and path.resolve(strict=True) == cache_alias.with_name("IE"))

    while pending:
        current = pending.pop()
        try:
            current_status = current.lstat()
            if stat.S_ISLNK(current_status.st_mode) or getattr(current_status, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                if known_cache_alias(current, current_status):
                    continue
                raise ValueError(f"评测资源目录包含链接：{current.relative_to(directory)}，属性={getattr(current_status, 'st_file_attributes', 0)}，重解析标记={getattr(current_status, 'st_reparse_tag', 0)}")
            children = list(current.iterdir())
        except FileNotFoundError:
            if current == directory:
                raise
            continue
        for path in children:
            try:
                status = path.lstat()
                if stat.S_ISLNK(status.st_mode) or getattr(status, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    if known_cache_alias(path, status):
                        continue
                    raise ValueError(f"评测资源目录包含链接：{path.relative_to(directory)}，属性={getattr(status, 'st_file_attributes', 0)}，重解析标记={getattr(status, 'st_reparse_tag', 0)}")
            except FileNotFoundError:
                # 编译器会删除中间产物；单次元数据快照避免多次查询之间的消失与误判。
                continue
            if stat.S_ISDIR(status.st_mode):
                pending.append(path)
            elif stat.S_ISREG(status.st_mode):
                count += 1
                size += status.st_size
            if count > max_files or size > max_bytes:
                raise ValueError("本次评测资源超过目录配额")
    return size


def scope_preserved(task: dict, before: dict, after: dict) -> bool:
    allowed = set(task["editable_files"])
    return all(before.get(name) == after.get(name) for name in before.keys() | after.keys() if name not in allowed)


def vue_program(task: dict, directory: Path, *, public: bool = False) -> str:
    modules = ROOT / "apps/desktop/node_modules"
    cases = task["cases"][:1] if public else task["cases"]
    # 使用现有编译器和 Vue SSR 执行真实组件，禁止仅按源码字符串猜测渲染结果。
    return f"""const fs=require('node:fs'),assert=require('node:assert/strict'),Module=require('node:module');
const ts=require({json.dumps(str(modules / 'typescript'))});
const sfc=require({json.dumps(str(modules / '@vue/compiler-sfc'))});
const vue=require({json.dumps(str(modules / 'vue'))});
const {{renderToString}}=require({json.dumps(str(modules / '@vue/server-renderer'))});
const base={json.dumps(str(directory))};
const original=Module.prototype.require;
Module.prototype.require=function(name){{return name==='vue'?vue:original.call(this,name)}};
require.extensions['.ts']=function(m,p){{m._compile(ts.transpileModule(fs.readFileSync(p,'utf8'),{{compilerOptions:{{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}}}).outputText,p)}};
require.extensions['.vue']=function(m,p){{const parsed=sfc.parse(fs.readFileSync(p,'utf8'),{{filename:p}});assert.equal(parsed.errors.length,0);const compiled=sfc.compileScript(parsed.descriptor,{{id:'s6',inlineTemplate:true}});m._compile(ts.transpileModule(compiled.content,{{compilerOptions:{{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}}}).outputText,p)}};
const component=require(base+'/src/Result.vue').default;
(async()=>{{for(const [input,expected] of {json.dumps(cases, ensure_ascii=False)}){{
const html=await renderToString(vue.createSSRApp(component,{{value:input}}));
const escaped=JSON.stringify(expected).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
assert.equal(html,'<output>'+escaped+'</output>');
}}}})().catch(error=>{{console.error(error.name);process.exitCode=1}});
"""


def rebuild(task: dict, directory: Path, *, runtime=None) -> dict:
    plain_path(directory, must_exist=False)
    for name in task["files"]:
        safe_relative(name)
    materialize(task, directory)
    if task.get("catalog_source") == "external_json" and task["family"] == "vue-typescript":
        (directory / ".s6-tools.json").write_text(json.dumps({
            "node_modules": str(runtime["root"] / "node_modules" if runtime else ROOT / "apps/desktop/node_modules")}), encoding="utf-8")
    elif task["family"] == "vue-typescript":
        (directory / "tests").mkdir()
        (directory / "tests/public.test.cjs").write_text(vue_program(task, directory, public=True), encoding="utf-8")
    elif task["family"] == "rust" and (configuration := (
        '[target.x86_64-pc-windows-msvc]\nlinker = ' + json.dumps(runtime["configuration"]["linker"]) +
        '\nrustflags = ' + json.dumps(runtime["configuration"]["rustflags"]) + '\n'
        if runtime else windows_rust_config())):
        (directory / ".cargo").mkdir()
        (directory / ".cargo/config.toml").write_text(configuration, encoding="utf-8")
    if task["family"] == "rust":
        toolchain = rust_toolchain()
        if toolchain is None:
            raise ValueError("Rust 工具链不可用")
        environment = isolated_environment(directory.parent)
        if not (directory / "Cargo.lock").exists():
            subprocess.run([str(toolchain / ("cargo.exe" if os.name == "nt" else "cargo")), "generate-lockfile", "--offline"],
                           cwd=directory, env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=True)
    if task["category"] == "boundary" and task["coding_goal"]:
        environment = isolated_environment(directory.parent)
        subprocess.run(["git", "init", "--quiet"], cwd=directory, env=environment, capture_output=True, timeout=10, check=True)
        subprocess.run(["git", "add", "--intent-to-add", "user-notes.txt"], cwd=directory, env=environment, capture_output=True, timeout=10, check=True)
    return snapshot(directory)


def execute(command: list[str], directory: Path, environment: dict, *, timeout: float = 30, output_limit: int = 64000) -> dict:
    if timeout <= 0 or not 1 <= output_limit <= 64000:
        raise ValueError("判定时长或输出上限无效")
    with tempfile.TemporaryFile() as output:
        try:
            with managed_process(command, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT) as process:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if os.fstat(output.fileno()).st_size > output_limit:
                        return {"passed": False, "exit_code": None, "reason": "judge_output_quota", "command": command}
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(command, timeout)
                    time.sleep(0.02)
                code = process.returncode
            output.seek(0)
            content = output.read(output_limit + 1)
            return {"passed": code == 0 and len(content) <= output_limit, "exit_code": code,
                    "output": content[:output_limit].decode("utf-8", errors="replace"), "truncated": len(content) > output_limit,
                    "reason": "judge_output_quota" if len(content) > output_limit else None, "command": command}
        except subprocess.TimeoutExpired:
            return {"passed": False, "exit_code": None, "reason": "judge_timeout", "command": command}


def judge(task: dict, directory: Path, area: Path, before: dict, *, isolation=None) -> dict:
    if task.get("catalog_source") == "external_json":
        from coding_acceptance_judge import judge_external

        return judge_external(task, directory, area, before, isolation=isolation)
    if isolation:
        raise ValueError("原内置题集仅支持既有公开校准；隔离判定请使用外部 JSON")
    directory = directory.resolve(strict=True)
    current = snapshot(directory)
    if not scope_preserved(task, before, current):
        return {"passed": False, "scope_preserved": False, "reason": "user_work_changed"}
    environment = isolated_environment(area)
    environment.pop("PYTHONPATH", None)
    hidden = area / ("judge-" + uuid.uuid4().hex)
    hidden.mkdir()
    if task["family"] == "python":
        key = "items" if task["category"] == "feature" else "result"
        program = f"import sys\nsys.path.insert(0,{str(directory)!r})\nfrom src.service import respond\n"
        program += "\n".join(f"assert respond({value!r}) == {{{key!r}: {expected!r}}}" for value, expected in task["cases"])
        if task["id"] == "PY02":
            program += "\ntry:\n    respond({'items':[], 'size':0})\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError('未拒绝无效页大小')\n"
        script = hidden / "judge.py"
        script.write_text(program, encoding="utf-8")
        result = execute([sys.executable, "-I", "-B", str(script)], directory, environment)
    elif task["family"] == "vue-typescript":
        script = hidden / "judge.cjs"
        script.write_text(vue_program(task, directory), encoding="utf-8")
        result = execute([shutil.which("node"), str(script)], directory, environment)
    else:
        source = hidden / "judge.rs"
        function = "evaluate" if task["category"] == "feature" else "solve"
        program = '#[path = ' + json.dumps(str(directory / "src/lib.rs")) + ']\nmod candidate;\n#[test]\nfn hidden() {\n'
        program += "\n".join(f"assert_eq!(candidate::{function}(&{value!r}), vec!{expected!r});" for value, expected in task["cases"]) + "\n}\n"
        source.write_text(program, encoding="utf-8")
        binary = hidden / ("judge.exe" if os.name == "nt" else "judge")
        result = execute([shutil.which("rustc"), "--edition=2021", "--test", str(source), "-o", str(binary)], directory, environment)
        if result["passed"]:
            result = execute([str(binary)], directory, environment)
    after = snapshot(directory)
    preserved = scope_preserved(task, before, after)
    unchanged = current == after
    return {**result, "scope_preserved": preserved, "validation_input_unchanged": unchanged,
            "input_sha256": current, "passed": result["passed"] and preserved and unchanged,
            "reason": "user_work_changed" if not preserved else "validation_changed_files" if not unchanged
            else None if result["passed"] else result.get("reason") or "assertion_failed"}


def verify_revision(task: dict) -> str:
    value = hashlib.sha256(json.dumps(task["files"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if value != task["source_revision"]:
        raise ValueError("任务初始版本摘要不符")
    return value
