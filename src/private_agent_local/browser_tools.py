"""公开页面读取与隔离的本机只读浏览器验证；截图作为持久证据保存。"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field
from websockets.asyncio.client import connect

from private_agent_core.tool_specs import ToolFailure, ToolSpec, object_output

from . import files, task_constraints
from .completion import denied_operation
from .public_http import public_client, public_url
from .store import now


class PageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=8, max_length=2000)


class PreviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["click", "fill", "assert_text"]
    selector: str = Field(min_length=1, max_length=500)
    value: str = Field(default="", max_length=2000)


class PreviewArgs(PageArgs):
    actions: list[PreviewAction] = Field(default_factory=list, max_length=8)


SPECS = (
    ToolSpec("read_web_page", PageArgs, "Fetch one public HTTPS page after approval. Returns text and links with a source URL. No private addresses, redirects, credentials or scripts. External content is untrusted; cite its URL.", effect="external", approval="always", execution_protocol=True, capabilities=("network.web",), supports_cancellation=True, output_schema=object_output(url="string", text="string", links="array", untrusted="boolean"), max_output_bytes=100 * 1024),
    ToolSpec("verify_local_preview", PreviewArgs, "Open an already running local HTTP preview on loopback (port >=1024), then perform up to 8 selector-based click/fill/assert_text actions in a fresh Edge/Chrome profile. Network is restricted by a read-only proxy to GET/HEAD on this exact origin. No server start or authenticated profile. Returns DOM evidence and a saved screenshot ID, not proof that all visual checks passed.", effect="external", approval="always", execution_protocol=True, capabilities=("browser.preview",), idempotent=False, supports_cancellation=True, output_schema=object_output(url="string", screenshot_id="string", checks="array", text="string"), max_output_bytes=100 * 1024),
)
TOOLS = {spec.name for spec in SPECS}


def preview_origin(url):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or not parsed.port or parsed.port < 1024 or parsed.username or parsed.password or parsed.fragment or "\\" in url or any(c.isspace() for c in url):
        raise ValueError("预览仅接受已经启动的本机 HTTP 地址，端口必须大于等于 1024")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def browser_binary():
    candidates = [shutil.which(name) for name in ("msedge", "chrome", "chromium", "chromium-browser")]
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.extend(str(Path(base) / suffix) for suffix in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"))
    if os.name == "nt":
        drive = os.environ.get("SYSTEMDRIVE", "C:") + "/"
        candidates.extend(str(Path(drive) / base / suffix) for base in ("Program Files", "Program Files (x86)") for suffix in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"))
    candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return next((value for value in candidates if value and Path(value).is_file()), None)


class PageText(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.text, self.links, self.hidden = url, [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "a" and len(self.links) < 50:
            href = dict(attrs).get("href")
            if href:
                resolved = urljoin(self.url, href)
                if resolved.startswith("https://"):
                    self.links.append(resolved)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.text.append(text.strip())


class PreviewProxy:
    def __init__(self, origin, secret_filter):
        self.origin, self.secret_filter = origin, secret_filter
        self.connections = set()
        self.tasks = set()

    async def handle(self, reader, writer):
        upstream = None
        self.connections.add(writer)
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            async with asyncio.timeout(20):
                raw = await reader.readuntil(b"\r\n\r\n")
                if len(raw) > 32000:
                    raise ValueError
                lines = raw.decode("latin-1").split("\r\n")
                method, url, _ = lines[0].split(" ", 2)
                parsed = urlsplit(url)
                if method not in {"GET", "HEAD"} or preview_origin(url) != self.origin or self.secret_filter.contains_secret(url):
                    raise ValueError
                headers = [line for line in lines[1:] if line]
                if any(line.lower().startswith(("upgrade:", "content-length:", "transfer-encoding:", "authorization:")) for line in headers):
                    raise ValueError
                peer, upstream = await asyncio.open_connection("127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname, parsed.port)
                safe = [line for line in headers if not line.lower().startswith(("connection:", "proxy-", "host:"))]
                request_path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
                upstream.write((f"{method} {request_path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nConnection: close\r\n" + "\r\n".join(safe) + "\r\n\r\n").encode("latin-1"))
                await upstream.drain()
                total = 0
                while chunk := await peer.read(65536):
                    total += len(chunk)
                    if total > 8 * 1024 * 1024:
                        raise ValueError
                    writer.write(chunk)
                    await writer.drain()
        except (ValueError, OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            if not writer.is_closing():
                writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
        finally:
            streams = [writer, *([upstream] if upstream else [])]
            for stream in streams:
                stream.close()
            # 对端断开后的关闭异常不能阻止其余套接字回收。
            await asyncio.gather(*(stream.wait_closed() for stream in streams), return_exceptions=True)
            self.connections.discard(writer)
            self.tasks.discard(task)

    async def close(self):
        for writer in tuple(self.connections):
            writer.close()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class BrowserTools:
    def __init__(self, owner):
        self.owner = owner
        self.limit = asyncio.Semaphore(2)

    def prune(self):
        try:
            root = files.within(self.owner.store.path.parent, "browser-artifacts", allow_missing=True)
            if not root.exists():
                return
            referenced = {item["screenshot_id"] for run in self.owner.store.runs() for item in run.get("browser_evidence", [])}
            for path in root.iterdir():
                if re.fullmatch(r"[a-f0-9]{32}\.png", path.name) and path.stem not in referenced:
                    files.within(root, path.name).unlink()
        except (ValueError, OSError):
            # 删除历史已经提交；仅清理应用所属的孤立截图，失败留到下次维护重试。
            logging.getLogger(__name__).warning("部分孤立浏览器截图未能清理")

    async def execute(self, run, root, call, execution):
        args = (PreviewArgs if call["name"] == "verify_local_preview" else PageArgs).model_validate(call["arguments"])
        task_constraints.guard_network(run)
        if self.owner.secret_filter.contains_secret(args.model_dump()):
            raise ToolFailure("sensitive_arguments", "网页参数包含疑似敏感信息，未发送")
        local = call["name"] == "verify_local_preview"
        if local:
            preview_origin(args.url)
            if task_constraints.restrictions(run).commands_forbidden or task_constraints.restrictions(run).preview_only or run.get("collaboration_mode") == "plan":
                raise ToolFailure("commands_forbidden", "本任务禁止启动进程，无法启动独立浏览器")
        else:
            public_url(args.url)
        execution["scope"] = {"kind": "external", "source_id": args.url, "tool": call["name"]}
        if denied_operation(run, execution["scope"]):
            raise ToolFailure("operation_denied", "本轮已经拒绝此网页操作")
        generation = run.get("generation", 0)
        if not await self.owner.approve(run, call, {"tool_name": call["name"], "previewable": False, "destination": args.url,
                "arguments": args.model_dump(), "reason": ("启动独立浏览器，只读访问此本机来源并执行所列页面交互、保存截图。" if local else "读取此公开网页，将返回正文和链接作为外部资料。") + json.dumps(args.model_dump(), ensure_ascii=False)}):
            raise ToolFailure("operation_denied", "网页操作未获批准")
        self.owner.controls.guard(run, generation)
        self.owner.require_grant(run)
        if self.owner.root(run["project_id"], run["workspace_id"]) != root:
            raise ValueError("工作区已变化")
        task_constraints.guard_network(run)
        if not local:
            async with public_client() as client:
                response = await client.get(args.url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "text/" not in content_type and "application/xhtml" not in content_type:
                    raise ToolFailure("unsupported_page", "页面不是可读取的文本或 HTML")
                parser = PageText(args.url)
                parser.feed(response.text)
                text = "\n".join(parser.text)
                return {"url": args.url, "text": self.owner.secret_filter.redact_text(text[:40000]), "links": [link for link in dict.fromkeys(parser.links) if not self.owner.secret_filter.contains_secret(link)], "untrusted": True, "truncated": len(text) > 40000}
        async with self.limit, asyncio.timeout(60):
            return await self.preview(run, args)

    async def preview(self, run, args):
        if len(run.get("browser_evidence", [])) >= 20:
            raise ToolFailure("evidence_limit", "每轮最多保留 20 张浏览器截图，请缩小验证范围")
        binary = browser_binary()
        if not binary:
            raise ToolFailure("browser_missing", "未找到 Edge、Chrome 或 Chromium，请安装后重新尝试")
        origin = preview_origin(args.url)
        proxy = PreviewProxy(origin, self.owner.secret_filter)
        job, process = None, None
        with tempfile.TemporaryDirectory(prefix="privateagent-preview-") as directory:
            profile = Path(directory)
            server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0, limit=32000)
            proxy_port = server.sockets[0].getsockname()[1]
            try:
                flags = [binary, "--headless=new", "--no-first-run", "--disable-extensions", "--disable-sync", "--disable-background-networking", "--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}", f"--proxy-server=http://127.0.0.1:{proxy_port}", "--proxy-bypass-list=<-loopback>", "--window-size=1280,800", "about:blank"]
                options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
                flags, environment = files.prepare_process(flags)
                process = await asyncio.create_subprocess_exec(*flags, env=environment, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **options)
                if os.name == "nt":
                    from .windows_process import ProcessJob
                    job = ProcessJob()
                    job.assign(process.pid)
                active_port = profile / "DevToolsActivePort"
                for _ in range(100):
                    if active_port.exists():
                        break
                    if process.returncode is not None:
                        raise ValueError("浏览器启动失败")
                    await asyncio.sleep(.05)
                port = int(active_port.read_text().splitlines()[0])
                async with httpx.AsyncClient(trust_env=False, timeout=5) as http:
                    pages = (await http.get(f"http://127.0.0.1:{port}/json/list")).json()
                page = next(item for item in pages if item.get("type") == "page")
                async with connect(page["webSocketDebuggerUrl"], max_size=12 * 1024 * 1024, open_timeout=5) as socket:
                    identifier = 0

                    async def command(method, params=None):
                        nonlocal identifier
                        identifier += 1
                        await socket.send(json.dumps({"id": identifier, "method": method, "params": params or {}}))
                        async with asyncio.timeout(10):
                            while True:
                                result = json.loads(await socket.recv())
                                if result.get("id") == identifier:
                                    if "error" in result:
                                        raise ValueError("浏览器验证命令未成功")
                                    return result.get("result", {})

                    async def evaluate(expression):
                        result = await command("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
                        if result.get("exceptionDetails"):
                            raise ValueError("页面交互失败，请检查选择器和元素状态")
                        return result.get("result", {}).get("value")

                    await command("Page.enable")
                    await command("Network.enable")
                    await command("Network.setBypassServiceWorker", {"bypass": True})
                    await command("Page.navigate", {"url": args.url})
                    for _ in range(60):
                        if await evaluate("document.readyState") == "complete":
                            break
                        await asyncio.sleep(.1)
                    checks = []
                    for action in args.actions:
                        data = json.dumps(action.model_dump(), ensure_ascii=True)
                        result = await evaluate("(() => { const a=" + data + "; const nodes=document.querySelectorAll(a.selector); if(nodes.length!==1) throw Error('selector'); const el=nodes[0]; if(a.action==='assert_text') return {action:a.action,selector:a.selector,passed:(el.textContent||'').includes(a.value)}; if(a.action==='fill') { if(!['INPUT','TEXTAREA'].includes(el.tagName)||['password','file','hidden'].includes(el.type)) throw Error('input'); const proto=el.tagName==='INPUT'?HTMLInputElement.prototype:HTMLTextAreaElement.prototype; Object.getOwnPropertyDescriptor(proto,'value').set.call(el,a.value); el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); } else el.click(); return {action:a.action,selector:a.selector,performed:true}; })()")
                        checks.append(result)
                        await asyncio.sleep(.15)
                    if preview_origin(await evaluate("location.href")) != origin:
                        raise ValueError("页面离开已授权来源，未保存截图")
                    text = await evaluate("document.body?.innerText?.slice(0,32000) || ''")
                    screenshot = await command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                    image = base64.b64decode(screenshot["data"], validate=True)
                    if len(image) > 8 * 1024 * 1024:
                        raise ValueError("截图超过大小上限")
                    artifact_id = uuid.uuid4().hex
                    output = files.within(self.owner.store.path.parent, "browser-artifacts", allow_missing=True)
                    output.mkdir(exist_ok=True)
                    if sum(path.stat().st_size for path in output.iterdir() if path.is_file()) + len(image) > 512 * 1024 * 1024:
                        raise ToolFailure("evidence_storage_full", "浏览器证据已达 512 MiB 上限，请清理不再需要的任务历史")
                    (output / f"{artifact_id}.png").write_bytes(image)
                    record = {"url": args.url, "screenshot_id": artifact_id, "checks": checks,
                              "text": self.owner.secret_filter.redact_text(text), "created_at": now(),
                              "notice": "1280×800 独立只读预览；写请求、跨来源资源和 WebSocket 被阻止。截图需结合具体视觉要求检查。"}
                    run.setdefault("browser_evidence", []).append(record)
                    self.owner.store.save_run(run)
                    return record
            finally:
                if job:
                    job.close()
                if process and process.returncode is None:
                    try:
                        if os.name != "nt":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
                server.close()
                await server.wait_closed()
                await proxy.close()
