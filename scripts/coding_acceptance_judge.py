"""独立比较候选输出；参考值不进入候选进程，原始验收输出不进入运行日志。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from coding_acceptance_schema import assessment_for, file_hash, fingerprint, plain_path
from run_coding_validation import ROOT, isolated_environment


def judge_environment(area: Path) -> dict:
    temporary = plain_path(area / "tmp", must_exist=False)
    temporary.mkdir(exist_ok=True)
    environment = isolated_environment(area)
    environment.pop("PYTHONPATH", None)
    return environment


def permission_probe(path: Path, area: Path) -> dict:
    from coding_acceptance_catalog import execute

    program = (
        "import hashlib,json,os,subprocess,sys\n"
        "identity=subprocess.check_output(['whoami','/user','/fo','csv','/nh']) if os.name=='nt' else str(os.geteuid()).encode()\n"
        "try:\n    open(sys.argv[1],'rb').close()\n    readable=True\n"
        "except PermissionError:\n    readable=False\n"
        "print(json.dumps({'identity_sha256':hashlib.sha256(identity).hexdigest(),'readable':readable,"
        "'write_access_reported':os.access(sys.argv[1],os.W_OK),'pid':os.getpid()}))\n"
    )
    environment = judge_environment(area)
    result = execute([sys.executable, "-I", "-B", "-c", program, str(path)], area, environment, timeout=10)
    if not result["passed"]:
        return {"verified": False, "reason": "permission_probe_failed"}
    try:
        observation = json.loads(result["output"])
    except (ValueError, KeyError):
        return {"verified": False, "reason": "permission_probe_invalid"}
    return {"verified": False, "reason": "trusted_execution_is_not_isolated", "probe": observation,
            "scope": "runner_child_same_inherited_identity", "target_sha256": file_hash(path)}


def observer(task: dict, cases: list, directory: Path, hidden: Path, exception_cases=(), *, runtime=None) -> tuple[Path, list[str], list]:
    inputs = [case[0] for case in cases]
    expected = [case[1] for case in cases]
    if task["family"] == "python":
        key = "items" if task["category"] == "feature" else "result"
        program = f"import json,sys\nsys.path.insert(0,{str(directory)!r})\nfrom src.service import respond\n"
        program += "def observe(value):\n    try:\n        return {'value':respond(value)}\n    except Exception as error:\n        return {'error':type(error).__name__}\n"
        inputs += [case["input"] for case in exception_cases]
        program += f"print(json.dumps([observe(value) for value in {inputs!r}],ensure_ascii=False,allow_nan=False))\n"
        expected = [{"value": {key: value}} for value in expected] + [{"error": case["error"]} for case in exception_cases]
        source = hidden / "observe.py"
        command = [str(runtime["executable"]) if runtime else sys.executable, "-I", "-X", "utf8", "-B", str(source)]
    elif task["family"] == "vue-typescript":
        modules = runtime["root"] / "node_modules" if runtime else ROOT / "apps/desktop/node_modules"
        program = f"""const fs=require('node:fs'),Module=require('node:module');
const ts=require({json.dumps(str(modules / 'typescript'))});
const sfc=require({json.dumps(str(modules / '@vue/compiler-sfc'))});
const vue=require({json.dumps(str(modules / 'vue'))});
const {{renderToString}}=require({json.dumps(str(modules / '@vue/server-renderer'))});
const original=Module.prototype.require;
Module.prototype.require=function(name){{return name==='vue'?vue:original.call(this,name)}};
require.extensions['.ts']=function(m,p){{m._compile(ts.transpileModule(fs.readFileSync(p,'utf8'),{{compilerOptions:{{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}}}).outputText,p)}};
require.extensions['.vue']=function(m,p){{const parsed=sfc.parse(fs.readFileSync(p,'utf8'),{{filename:p}});if(parsed.errors.length)throw Error('组件解析失败');const compiled=sfc.compileScript(parsed.descriptor,{{id:'s6',inlineTemplate:true}});m._compile(ts.transpileModule(compiled.content,{{compilerOptions:{{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}}}).outputText,p)}};
const component=require({json.dumps(str(directory / 'src/Result.vue'))}).default;
(async()=>{{const output=[];for(const input of {json.dumps(inputs, ensure_ascii=False)}){{output.push(await renderToString(vue.createSSRApp(component,{{value:input}})))}}console.log(JSON.stringify(output))}})().catch(()=>{{process.exitCode=1}});
"""
        def escaped(value):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
        expected = ["<output>" + escaped(value) + "</output>" for value in expected]
        source = hidden / "observe.cjs"
        command = ([str(runtime["executable"]), "--preserve-symlinks", "--preserve-symlinks-main", str(source)]
                   if runtime else [shutil.which("node"), str(source)])
    else:
        function = "evaluate" if task["category"] == "feature" else "solve"
        program = '#[path = ' + json.dumps(str(directory / "src/lib.rs")) + ']\nmod candidate;\nfn main() {\n'
        values = ",".join(f"candidate::{function}(&{value!r})" for value in inputs)
        program += 'let output: Vec<Vec<i64>> = vec![' + values + '];\nprintln!("{:?}",output);\n}\n'
        source = hidden / "observe.rs"
        output = directory / "target/s6-observer" if runtime else hidden
        output.mkdir(parents=True, exist_ok=True)
        command = [str(output / ("observe.exe" if os.name == "nt" else "observe"))]
    source.write_text(program, encoding="utf-8", newline="\n")
    return source, command, expected


def judge_external(task: dict, directory: Path, area: Path, before: dict, *, isolation=None) -> dict:
    from coding_acceptance_catalog import execute, scope_preserved, snapshot

    plain_path(directory)
    current = snapshot(directory)
    binding = {"assessment_sha256": task["assessment_sha256"], "task_sha256": task["task_sha256"],
               "candidate_sha256": fingerprint(current)}
    if not scope_preserved(task, before, current):
        return {"passed": False, "scope_preserved": False, "reason": "user_work_changed",
                "binding": binding, "verifier_sha256": file_hash(Path(__file__))}
    assessment = assessment_for(task)
    runtime = isolation.runtime(task["family"]) if isolation else None
    if isolation:
        isolation.verify()
        hidden = isolation.observer_directory(task["family"])
        candidate = plain_path(area / ("c-" + uuid.uuid4().hex[:12]), must_exist=False)
        candidate.mkdir()
        # 验收只运行冻结的普通文件副本；原 Agent 目录不挂入候选进程。
        for name in current:
            target = candidate / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(plain_path(directory / name), target)
    else:
        hidden = plain_path(area / ("judge-" + uuid.uuid4().hex), must_exist=False)
        hidden.mkdir()
        candidate = directory
    source, command, expected = observer(task, assessment["cases"], candidate, hidden, assessment["exception_cases"], runtime=runtime)
    if isolation:
        isolation.seal_observer(task["family"], source)
    observer_hash = file_hash(source)
    verifier_hash = file_hash(Path(__file__))
    environment = judge_environment(hidden) if not isolation else None
    def run_command(argv, timeout, output_limit):
        if isolation:
            return isolation.execute(task["family"], argv, candidate, timeout=timeout, output_limit=output_limit)
        return execute(argv, candidate, environment, timeout=timeout, output_limit=output_limit)

    deadline = time.monotonic() + assessment["timeout_seconds"]
    if task["family"] == "rust":
        compiler = str(runtime["executable"]) if runtime else shutil.which("rustc")
        flags = (["-C", "linker=" + runtime["configuration"]["linker"], *runtime["configuration"]["rustflags"]] if runtime else [])
        result = run_command([compiler, "--edition=2021", str(source), "-o", command[0], *flags],
                             timeout=max(0.001, deadline - time.monotonic()), output_limit=assessment["output_bytes"])
    else:
        result = {"passed": True}
    if result["passed"]:
        result = run_command(command, timeout=max(0.001, deadline - time.monotonic()), output_limit=assessment["output_bytes"])
    reason = result.get("reason") or (None if result["passed"] else "candidate_failed")
    try:
        if result["passed"] and fingerprint(json.loads(result["output"])) != fingerprint(expected):
            reason = "assertion_failed"
    except (ValueError, RecursionError):
        reason = "invalid_candidate_output"
    for name, fragments in assessment["forbidden_fragments"].items():
        if any(value in (directory / name).read_text(encoding="utf-8") for value in fragments):
            reason = "refactor_constraint_failed"
    try:
        if (file_hash(source) != observer_hash or file_hash(Path(__file__)) != verifier_hash
                or file_hash(Path(task["assessment_path"])) != task["assessment_sha256"]):
            reason = "judge_changed_during_validation"
    except (ValueError, OSError):
        reason = "judge_changed_during_validation"
    after = snapshot(directory)
    if isolation:
        isolated_after = snapshot(candidate)
        for generated in ("observe.exe", "observe.pdb"):
            isolated_after.pop(generated, None)
        # TEMP 和编译产物属于执行区，源文件任何变化仍使判定失败。
        isolated_after = {key: value for key, value in isolated_after.items() if not key.startswith("tmp/")}
        if isolated_after != current:
            reason = "validation_changed_files"
        isolation.verify()
    preserved = scope_preserved(task, before, after)
    if not preserved:
        reason = "user_work_changed"
    elif current != after:
        reason = "validation_changed_files"
    # 返回状态和摘要，禁止把候选 stdout、异常正文、隐藏输入或期望值写入公开证据。
    return {"passed": reason is None, "reason": reason, "scope_preserved": preserved,
            "validation_input_unchanged": current == after, "input_sha256": current,
            "binding": binding, "observer_sha256": observer_hash, "verifier_sha256": verifier_hash,
            "output_sha256": hashlib.sha256(result.get("output", "").encode()).hexdigest(),
            "exit_code": result.get("exit_code"), "isolation_verified": isolation is not None,
            "execution_profile": result.get("profile"), "execution_host_sha256": result.get("host_sha256"),
            "runtime_sha256": isolation.identity() if isolation else None}
