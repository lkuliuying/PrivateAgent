"""阶段 B 的 Windows 判定后端：仅授权本次复制的工具和候选目录。"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import sys
import time
import tomllib
import uuid
from pathlib import Path

from coding_acceptance_schema import fingerprint, plain_path, read_json
from run_coding_validation import ROOT, isolated_environment


def tree_hash(root: Path) -> dict:
    result, size = {}, 0
    for path in sorted(root.rglob("*")):
        plain_path(path)
        if path.is_file():
            size += path.stat().st_size
            if len(result) >= 50000 or size > 2 * 1024**3:
                raise ValueError("隔离工具副本超过 50000 文件或 2 GiB")
            with path.open("rb") as stream:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def copy_tree(source: Path, target: Path, *, excluded=()) -> None:
    plain_path(source)
    target.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.name in excluded:
            continue
        plain_path(path)
        if path.is_dir():
            copy_tree(path, target / path.name, excluded=excluded)
        elif path.is_file():
            shutil.copyfile(path, target / path.name)
        else:
            raise ValueError("工具副本只接受普通文件")


def copy_python(target: Path) -> Path:
    # 已安装解释器可能通过 uv 的版本链接选择；先固定真实安装目录，再复制普通文件。
    base = plain_path(Path(sys.base_prefix).resolve(strict=True))
    copy_tree(base / "Lib", target / "Lib", excluded={"site-packages", "__pycache__", "test", "tests", "ensurepip"})
    copy_tree(base / "DLLs", target / "DLLs")
    for path in base.glob("*.dll"):
        shutil.copyfile(plain_path(path), target / path.name)
    executable = target / "s6-python.exe"
    shutil.copyfile(plain_path(base / "python.exe"), executable)
    # 独立解释器只读取复制的标准库及公开测试依赖，不继承开发虚拟环境。
    (target / "s6-python._pth").write_text(".\nLib\nDLLs\nLib/site-packages\nimport site\n", encoding="utf-8")
    packages = target / "Lib/site-packages"
    packages.mkdir()
    for name in ("pytest", "_pytest", "pluggy", "iniconfig", "packaging", "colorama", "pygments"):
        spec = importlib.util.find_spec(name)
        if not spec or not spec.origin:
            raise ValueError("缺少公开 Python 测试依赖：" + name)
        copy_tree(Path(spec.origin).resolve(strict=True).parent, packages / name, excluded={"__pycache__"})
    for name in ("pytest", "pluggy", "iniconfig", "packaging", "colorama", "pygments"):
        distribution = importlib.metadata.distribution(name)
        metadata = next(path for path in distribution.files if path.name == "METADATA")
        source = Path(distribution.locate_file(metadata)).resolve(strict=True).parent
        copy_tree(source, packages / source.name)
    shim = importlib.util.find_spec("py")
    if not shim or not shim.origin:
        raise ValueError("缺少 pytest 的 py 兼容模块")
    shutil.copyfile(plain_path(Path(shim.origin).resolve(strict=True)), packages / "py.py")
    shutil.copyfile(ROOT / "scripts/coding_acceptance_pytest.py", target / "s6_pytest_boundary.py")
    # 保留标准目录收集与根 conftest，仅省去已知父目录的类型探测。
    (target / "python.cmd").write_text(
        '@echo off\r\nset "PYTEST_ADDOPTS=--confcutdir=."\r\nset "PYTEST_PLUGINS=s6_pytest_boundary"\r\n'
        '"%~dp0s6-python.exe" %*\r\n', encoding="ascii")
    return executable


def copy_node(target: Path) -> Path:
    executable = target / "node.exe"
    source = shutil.which("node")
    if not source:
        raise ValueError("缺少 Node.js")
    shutil.copyfile(plain_path(Path(source)), executable)
    modules = ROOT / "apps/desktop/node_modules"
    pending = ["typescript", "vue", "@vue/compiler-sfc", "@vue/server-renderer"]
    copied = set()
    while pending:
        name = pending.pop()
        if name in copied:
            continue
        if not name or any(part in {"", ".", ".."} for part in name.split("/")) or "\\" in name or ":" in name:
            raise ValueError("Node 依赖路径无效")
        folder = plain_path(modules / name)
        metadata = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        copy_tree(folder, target / "node_modules" / name, excluded={"__pycache__"})
        pending.extend(metadata.get("dependencies", {}))
        copied.add(name)
        if len(copied) > 100:
            raise ValueError("Vue 判定依赖超过 100 包")
    npm = plain_path(Path(source).parent / "node_modules/npm")
    copy_tree(npm, target / "node_modules/npm")
    (target / "npm.cmd").write_text(
        '@echo off\r\nfor %%I in ("%TEMP%\\..\\..\\..\\..") do set "LOCALAPPDATA=%%~fI"\r\n'
        'set "NODE_OPTIONS=--preserve-symlinks --preserve-symlinks-main --test-isolation=none"\r\n'
        '"%~dp0node.exe" "%~dp0node_modules\\npm\\bin\\npm-cli.js" %*\r\n', encoding="ascii")
    return executable


def copy_rust(target: Path) -> tuple[Path, dict]:
    from coding_acceptance_catalog import rust_toolchain, windows_rust_config

    toolchain = rust_toolchain()
    if toolchain is None:
        raise ValueError("缺少 Rust 工具链")
    (target / "bin").mkdir()
    for path in toolchain.iterdir():
        if path.suffix.lower() == ".dll" or path.name in {"rustc.exe", "rustdoc.exe", "cargo.exe"}:
            shutil.copyfile(plain_path(path), target / "bin" / path.name)
    copy_tree(toolchain.parent / "lib", target / "lib")
    config = tomllib.loads(windows_rust_config())["target"]["x86_64-pc-windows-msvc"]
    linker = Path(config["linker"])
    (target / "link").mkdir()
    for path in linker.parent.iterdir():
        if path.suffix.lower() == ".dll" or path.name in {"link.exe", "mspdbsrv.exe"}:
            shutil.copyfile(plain_path(path), target / "link" / path.name)
    libraries = []
    for index, value in enumerate(config["rustflags"]):
        if not value.startswith("-Lnative="):
            raise ValueError("未知 Rust 链接配置")
        destination = target / ("native-" + str(index))
        source = Path(value.removeprefix("-Lnative="))
        destination.mkdir()
        names = ({"kernel32.lib", "ntdll.lib", "userenv.lib", "ws2_32.lib", "dbghelp.lib", "advapi32.lib", "bcrypt.lib"}
                 if index == 1 else {"msvcrt.lib", "libcmt.lib", "oldnames.lib", "vcruntime.lib", "libvcruntime.lib",
                                      "legacy_stdio_definitions.lib", "legacy_stdio_wide_specifiers.lib"}
                 if index == 0 else {"ucrt.lib", "libucrt.lib"})
        for name in names:
            shutil.copyfile(plain_path(source / name), destination / name)
        libraries.append("-Lnative=" + str(destination))
    (target / "cargo.cmd").write_text(
        '@echo off\r\nset "CARGO_TARGET_DIR=%TEMP%\\s6-target"\r\n"%~dp0bin\\cargo.exe" %*\r\n', encoding="ascii")
    # 入口放在副本根目录，现有 SandboxLease 只需授权这个副本。
    (target / "rustc.cmd").write_text('@echo off\r\n"%~dp0bin\\rustc.exe" %*\r\n', encoding="ascii")
    return target / "rustc.cmd", {"linker": str(target / "link/link.exe"), "rustflags": libraries}


def token_program(targets: list[Path], public: Path) -> str:
    """只输出权限结果和令牌摘要；探针不输出被保护文件的内容。"""
    return (
        "import ctypes as c,json,hashlib,os;from ctypes import wintypes as w\n"
        "k=c.WinDLL('kernel32',use_last_error=True);a=c.WinDLL('advapi32',use_last_error=True)\n"
        "k.GetCurrentProcess.restype=w.HANDLE;k.CloseHandle.argtypes=[w.HANDLE]\n"
        "a.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)]\n"
        "a.GetTokenInformation.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]\n"
        "a.ConvertSidToStringSidW.argtypes=[c.c_void_p,c.POINTER(w.LPWSTR)];k.LocalFree.argtypes=[c.c_void_p]\n"
        "t=w.HANDLE();assert a.OpenProcessToken(k.GetCurrentProcess(),8,c.byref(t))\n"
        "flag=w.DWORD();size=w.DWORD();assert a.GetTokenInformation(t,29,c.byref(flag),4,c.byref(size))\n"
        "caps=c.create_string_buffer(4096);assert a.GetTokenInformation(t,30,caps,4096,c.byref(size))\n"
        "info=c.create_string_buffer(4096);assert a.GetTokenInformation(t,31,info,4096,c.byref(size))\n"
        "sid=w.LPWSTR();assert a.ConvertSidToStringSidW(c.c_void_p.from_buffer(info),c.byref(sid))\n"
        "identity=hashlib.sha256(sid.value.encode()).hexdigest();k.LocalFree(c.cast(sid,c.c_void_p));k.CloseHandle(t)\n"
        "def access(path,mode):\n"
        "    try:\n        with open(path,mode): pass\n        return True\n"
        "    except PermissionError: return False\n"
        f"targets={list(map(str, targets))!r}\n"
        f"print(json.dumps({{'appcontainer':flag.value,'capabilities':w.DWORD.from_buffer(caps).value,"
        f"'identity_sha256':identity,'public_read':access({str(public)!r},'rb'),"
        "'targets':[{'read':access(p,'rb'),'write':access(p,'r+b')} for p in targets]}))\n"
    )


class WindowsIsolation:
    """复用原生宿主和可恢复租约，不创建系统用户或授权共享工具目录。"""

    def __init__(self, directory: Path):
        if os.name != "nt":
            raise ValueError("阶段 B 当前隔离后端仅验证 Windows AppContainer")
        self.directory = plain_path(directory, must_exist=False)
        self.directory.mkdir(exist_ok=False)
        self.runtimes = {}
        self.agent_backend = None
        self.protected = set()
        self.host_sha256 = None

    def runtime(self, family: str) -> dict:
        if family in self.runtimes:
            return self.runtimes[family]
        if family not in {"python", "vue-typescript", "rust"}:
            raise ValueError("未知隔离语言")
        # MSVC 链接器仍受部分长路径限制，实验目录已唯一，内部目录使用固定短名。
        root = self.directory / {"python": "p", "vue-typescript": "v", "rust": "r"}[family]
        root.mkdir()
        config = None
        if family == "python":
            executable = copy_python(root)
        elif family == "vue-typescript":
            executable = copy_node(root)
        else:
            executable, config = copy_rust(root)
        result = {"root": root, "executable": executable, "configuration": config, "files": tree_hash(root)}
        self.runtimes[family] = result
        return result

    def agent_runtime(self, family: str) -> dict:
        # Agent 的共享工具副本永不包含判定侧生成的观察程序或隐藏输入。
        if self.agent_backend is None:
            self.agent_backend = WindowsIsolation(self.directory / "a")
        return self.agent_backend.runtime(family)

    def verify(self) -> None:
        if self.agent_backend:
            self.agent_backend.verify()
        if self.host_sha256 is not None:
            from private_agent_local.executor import host_path, verify_host
            if verify_host(host_path()) != self.host_sha256:
                raise ValueError("隔离执行宿主发生变化")
        for runtime in self.runtimes.values():
            actual = tree_hash(runtime["root"])
            if actual != runtime["files"]:
                raise ValueError("隔离运行时副本发生变化")

    def identity(self) -> dict:
        result = {family: fingerprint({key: value for key, value in runtime["files"].items() if not key.startswith("observers/")})
                  for family, runtime in self.runtimes.items()}
        if self.agent_backend:
            result["agent"] = self.agent_backend.identity()
        return result

    def local_appdata(self) -> Path:
        from private_agent_local.windows_process import profile_environment

        # 只经 Windows API 定位目录，不读取用户设置；受限子进程无法读取其他应用材料。
        return Path(profile_environment()["LOCALAPPDATA"])

    def observer_directory(self, family: str) -> Path:
        root = self.runtime(family)["root"] / "observers" / uuid.uuid4().hex[:12]
        root.mkdir(parents=True)
        return root

    def seal_observer(self, family: str, path: Path) -> None:
        runtime = self.runtime(family)
        plain_path(path)
        if not path.is_relative_to(runtime["root"] / "observers"):
            raise ValueError("观察程序不在指定的只读副本中")
        name = path.relative_to(runtime["root"]).as_posix()
        if name in runtime["files"]:
            raise ValueError("观察程序不可覆盖")
        runtime["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()

    def environment(self, family: str, area: Path) -> dict:
        runtime = self.runtime(family)
        environment = isolated_environment(area)
        environment.pop("PYTHONPATH", None)
        system = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        environment["PATH"] = os.pathsep.join(map(str, [runtime["root"], runtime["root"] / "bin", system / "System32", system]))
        environment["USERPROFILE"] = environment["HOME"] = str(area)
        environment["APPDATA"] = environment["LOCALAPPDATA"] = str(self.directory.parent / "h")
        (self.directory.parent / "h").mkdir(exist_ok=True)
        (area / "tmp").mkdir(exist_ok=True)
        return environment

    def execute(self, family: str, argv: list[str], root: Path, *, timeout: float, output_limit: int = 64000) -> dict:
        return asyncio.run(self._execute(family, argv, root, timeout=timeout, output_limit=output_limit))

    async def _execute(self, family, argv, root, *, timeout, output_limit):
        from private_agent_core.execution.contracts import ExecStartParams
        from private_agent_core.execution.exec_host_client import ExecHostClient
        from private_agent_local.executor import host_path, verify_host
        from private_agent_local.windows_sandbox import SandboxLease, runtime_roots

        if not 0 < timeout <= 30 or type(output_limit) is not int or not 1 <= output_limit <= 64000:
            raise ValueError("隔离执行预算无效")
        plain_path(root)
        runtime = self.runtime(family)
        if root.is_relative_to(self.directory) or self.directory.is_relative_to(root):
            raise ValueError("候选目录不得覆盖隔离控制区")
        if any(path.is_relative_to(root) or path.is_relative_to(runtime["root"]) for path in self.protected):
            raise ValueError("验收材料落入本次候选可访问的授权范围")
        environment = self.environment(family, root)
        roots = runtime_roots([str(runtime["executable"])], environment)
        if roots != [runtime["root"]]:
            raise ValueError("拒绝授权本次工具副本以外的目录")
        host = host_path()
        host_hash = verify_host(host)
        if self.host_sha256 is not None and host_hash != self.host_sha256:
            raise ValueError("隔离执行宿主发生变化")
        self.host_sha256 = host_hash
        if Path(argv[0]).suffix.lower() in {".cmd", ".bat"}:
            if any(any(char in value for char in '&|<>^%!\r\n"') for value in argv):
                raise ValueError("批处理参数包含不支持的 shell 字符")
            argv = [environment.get("COMSPEC", r"C:\Windows\System32\cmd.exe"), "/d", "/s", "/c",
                    " ".join('"' + value + '"' for value in argv)]
        client = ExecHostClient([str(host)], env=environment)
        lease = None
        output, reason, code, profile = bytearray(), None, None, None
        started = time.monotonic()
        try:
            health = await client.start()
            if not health.sandbox_available or health.sandbox_profile_protocol != 1 or not health.process_tree_termination:
                raise ValueError("执行宿主缺少隔离及后代回收契约")
            lease = await SandboxLease.prepare(root, [str(runtime["executable"])], environment,
                                               directory=self.directory / "leases")
            lease.bind(client.pid)
            profile = lease.name
            # Windows 原生程序会按 LOCALAPPDATA 派生容器临时目录，必须与租约实际创建的位置一致。
            lease.environment["LOCALAPPDATA"] = str(Path(lease.environment["TEMP"]).parents[3])
            execution_id = str(uuid.uuid4())
            await client.start_execution(ExecStartParams(execution_id=execution_id, argv=argv, cwd=str(root),
                env_diff=lease.environment, timeout_ms=max(1, int(timeout * 1000)), output_limit_bytes=max(1024, output_limit),
                sandbox_policy_hash=fingerprint({"argv": argv, "root": str(root), "runtime": fingerprint(runtime["files"])}),
                network_policy="none", appcontainer=True, appcontainer_profile=profile))
            async with asyncio.timeout(timeout + 5):
                while True:
                    event = await client.next_event(timeout=1)
                    if event is None:
                        client.ensure_alive()
                        continue
                    if event.execution_id != execution_id:
                        raise ValueError("隔离宿主返回其他执行的事件")
                    if event.truncated or event.notification.value == "execution/output/truncated":
                        reason = "judge_output_quota"
                        break
                    if event.data:
                        data = event.data.encode("utf-8")
                        if len(output) + len(data) > output_limit:
                            reason = "judge_output_quota"
                            break
                        output.extend(data)
                    if event.notification.value == "execution/failed":
                        reason = "isolation_execution_failed"
                        break
                    if event.notification.value == "execution/exited":
                        code = event.exit_code
                        reason = "judge_timeout" if event.cancelled_by_timeout else None if code == 0 else "candidate_failed"
                        break
        except TimeoutError:
            reason = "judge_timeout"
        finally:
            try:
                await client.close()
            finally:
                if lease:
                    await asyncio.to_thread(lease.close)
        return {"passed": reason is None and code == 0, "reason": reason, "exit_code": code,
                "output": output.decode("utf-8", errors="replace"), "profile": profile, "host_sha256": host_hash,
                "elapsed_seconds": round(time.monotonic() - started, 3)}

    def probe(self, protected: list[Path], area: Path) -> dict:
        self.protected.update(plain_path(path) for path in protected)
        runtime = self.runtime("python")
        project = plain_path(area, must_exist=False)
        project.mkdir()
        public = project / "public.txt"
        public.write_text("PUBLIC_SYNTHETIC", encoding="ascii")
        source = project / "probe.py"
        source.write_text(token_program(protected, public), encoding="utf-8")
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in protected]
        result = self.execute("python", [str(runtime["executable"]), "-I", "-B", str(source)], project, timeout=10)
        try:
            observed = json.loads(result["output"]) if result["passed"] else {}
        except ValueError:
            observed = {}
        unchanged = before == [hashlib.sha256(path.read_bytes()).hexdigest() for path in protected]
        verified = (observed.get("appcontainer") == 1 and observed.get("capabilities") == 0
                    and observed.get("public_read") is True and len(observed.get("targets", [])) == len(protected)
                    and bool(protected) and all(value == {"read": False, "write": False} for value in observed["targets"]) and unchanged)
        return {"verified": verified, "reason": None if verified else "isolation_probe_failed",
                "scope": "appcontainer_candidate_process", "observation": observed, "protected_sha256": before,
                "host_sha256": result["host_sha256"], "runtime_sha256": self.identity()}

    def agent_probe(self, protected: list[Path], area: Path, *, bundle=None) -> dict:
        from coding_acceptance_transport import Fixture, RuntimeClient, reply
        from run_coding_acceptance import events, poll_run

        area.mkdir()
        project = area / "project"
        project.mkdir()
        public = project / "public.txt"
        public.write_text("PUBLIC_SYNTHETIC_READ_ALLOWED", encoding="ascii")
        source = project / "probe.py"
        source.write_text(token_program(protected, public) + "\nimport time;time.sleep(0.5)\n", encoding="utf-8")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        before = [hashlib.sha256(plain_path(path).read_bytes()).hexdigest() for path in protected]
        runtime = self.agent_runtime("python")
        command = ["python", "-I", "-B", "probe.py"]
        approvals = set()
        grants = []
        with Fixture() as fixture:
            fixture.responses.extend([
                reply(name="read_code_file", arguments={"rel_path": "../outside-assessment.json"}),
                reply(name="read_code_file", arguments={"rel_path": "public.txt"}),
                reply(name="exec_command", arguments={"argv": command, "execution_mode": "restricted",
                      "network_policy": "none", "yield_time_ms": 30000, "timeout_ms": 10000}),
                *[reply("文件和命令的实际结果见运行证据；本次仅核对隔离权限。") for _ in range(4)],
            ])
            with RuntimeClient(area, fixture, bundle=bundle, tool_paths=[runtime["root"]],
                               tool_local_appdata=self.local_appdata()) as client:
                client.request("/identity", "POST")
                project_info = client.request("/projects", "POST", {"name": "阶段 B 合成隔离探针", "root_path": str(project)})
                workspace = client.request(f"/projects/{project_info['id']}/workspaces")[0]
                binding = {"project_id": project_info["id"], "workspace_id": workspace["id"]}
                session = client.request("/sessions", "POST", {**binding, "title": "阶段 B 隔离预检"})
                run = client.request("/agent-runs", "POST", {**binding, "session_id": session["id"],
                    "message": "执行合成权限探针", "model_profile_id": "s6-profile", "execution_contract_version": "1.0"})

                def approve(current):
                    for journal in (area / "records").glob("*/sandbox-leases/*.json"):
                        try:
                            paths = read_json(journal)["paths"]
                        except FileNotFoundError:
                            continue
                        if paths not in grants:
                            grants.append(paths)
                    for item in client.request(f"/agent-runs/{run['id']}/approvals"):
                        if item["status"] != "pending" or item["id"] in approvals:
                            continue
                        preview = client.request(f"/agent-runs/{run['id']}/approvals/{item['id']}/preview")
                        if (preview.get("argv") != command or preview.get("execution_mode") != "restricted"
                                or preview.get("network_policy") != "none" or preview.get("cwd") != "."):
                            raise ValueError("隔离预检收到意外审批；不批准降级执行")
                        approvals.add(item["id"])
                        client.request(f"/agent-runs/{run['id']}/approvals/{item['id']}/approve", "POST")

                run, observation = poll_run(client, run, deadline=time.monotonic() + 30, on_active=approve)
                execution = client.request(f"/agent-runs/{run['id']}/executions")
                managed = client.request(f"/sessions/{session['id']}/executions")["items"]
                history = events(client, run)
        observations = []

        def collect(value):
            if isinstance(value, dict):
                if "appcontainer" in value and "targets" in value:
                    observations.append(value)
                else:
                    for item in value.values():
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, str):
                for line in value.splitlines():
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(item, (dict, list)):
                        collect(item)

        collect(execution)
        read_denied = any(item["type"] == "tool.failed" and item["payload"].get("name") == "read_code_file" for item in history)
        public_read = "PUBLIC_SYNTHETIC_READ_ALLOWED" in json.dumps(execution)
        unchanged = (before == [hashlib.sha256(path.read_bytes()).hexdigest() for path in protected]
                     and source_hash == hashlib.sha256(source.read_bytes()).hexdigest())
        expected_grants = [{"path": str(project), "write": True}, {"path": str(runtime["root"]), "write": False}]
        grants_verified = bool(grants) and all(paths == expected_grants for paths in grants)
        verified = (run["status"] == "completed" and observation["terminal_observed"] and len(approvals) == 1
                    and len(managed) == 1 and all(item.get("execution_mode") == "restricted" and item.get("network_policy") == "none"
                        and item.get("host_sha256") for item in managed)
                    and read_denied and public_read and unchanged and grants_verified and bool(observations)
                    and all(item.get("appcontainer") == 1 and item.get("capabilities") == 0
                            and item.get("public_read") is True and len(item.get("targets", [])) == len(protected)
                            and all(target == {"read": False, "write": False} for target in item["targets"])
                            for item in observations))
        return {"verified": verified, "scope": "actual_agent_ipc_restricted_command", "run_status": run["status"],
                "run_error_code": run.get("error_code"), "termination": observation,
                "read_tool_denied": read_denied, "public_read": public_read, "observations": observations,
                "protected_sha256": before, "source_sha256": source_hash, "events_sha256": fingerprint(history),
                "executions_sha256": fingerprint(execution), "approval_count": len(approvals),
                "grant_scope_verified": grants_verified, "grant_paths": grants,
                "managed": [{key: item.get(key) for key in ("execution_mode", "network_policy", "host_sha256", "status", "error")} for item in managed]}
