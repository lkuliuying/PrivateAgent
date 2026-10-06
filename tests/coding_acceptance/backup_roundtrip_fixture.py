"""浏览器备份往返的真实 ASGI 夹具，只使用 .run 内合成数据。"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import uuid
from contextlib import AsyncExitStack
from pathlib import Path

from test_attachment_media import image_bytes, text_pdf
from test_direct_models import configure, desktop

from private_agent_local.attachments import read_blob
from private_agent_local.drafts import DraftData, Drafts, DraftWrite


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


async def seed(context, root, temperature):
    models, app, client, _, _ = context
    identifier = await configure(client)
    response = await client.put("/model-settings", json={"llm_temperature": temperature})
    response.raise_for_status()
    project_root = root / "source-project"
    project_root.mkdir()
    response = await client.post("/projects", json={"name": "中文备份项目", "root_path": str(project_root)})
    response.raise_for_status()
    project = response.json()
    workspace = (await client.get(f"/projects/{project['id']}/workspaces")).json()[0]
    response = await client.post("/sessions", json={"project_id": project["id"], "workspace_id": workspace["id"],
                                                    "kind": "coding", "title": "中文历史与未发送草稿"})
    response.raise_for_status()
    session = response.json()
    runtime, draft_id = app.state.desktop.runtime, uuid.uuid4().hex
    store = runtime.store
    store.update("session", session["id"], model_profile_id=identifier)
    materials = {"中文说明.txt": "中文材料，保留换行与小数 0.0。\n第二行。".encode(),
                 "中文图片.png": image_bytes(), "中文文档.pdf": text_pdf()}
    attachments = []
    for name, content in materials.items():
        source = project_root / name
        source.write_bytes(content)
        attachments.append(store.attachments.stage(source, draft_id, project["id"], workspace["id"], session["id"],
                                                   secret_filter=runtime.secret_filter))
    with store.transaction():
        message = store.create("message", {"session_id": session["id"], "role": "user", "content": "请查看中文历史附件"})
        store.attachments.bind([item["id"] for item in attachments], draft_id, session, message["id"])
        store.save_run({"id": uuid.uuid4().hex, "session_id": session["id"], "project_id": project["id"], "workspace_id": workspace["id"],
                        "status": "completed", "cost_usd": 0.0, "output": "中文历史结果，费用为零", "permission_mode": "confirm"})
    # 同时覆盖历史附件与独立草稿附件，不在备份包上修改任何内容或摘要。
    draft_id = uuid.uuid4().hex
    draft_items = []
    for name, content in materials.items():
        source = project_root / ("草稿" + name)
        source.write_bytes(content)
        draft_items.append(store.attachments.stage(source, draft_id, project["id"], workspace["id"], session["id"],
                                                   secret_filter=runtime.secret_filter))
    key = f"pa_coding_draft_v2_{project['id']}_{workspace['id']}_{session['id']}"
    Drafts(store).put(key, DraftWrite(revision=0, mutation_id=uuid.uuid4().hex,
                                    data=DraftData(text="中文未发送草稿", draftId=draft_id, attachments=draft_items,
                                                   clientRequestId="must-not-replay", requestSignature="must-not-restore")))
    assert models.catalog.data["parameters"]["llm_temperature"] == temperature


def snapshot(context):
    models, app, _, account_calls, provider_calls = context
    store = app.state.desktop.runtime.store
    attachments = []
    for (identifier,) in store.db.execute("SELECT id FROM task_attachments ORDER BY id"):
        item = store.attachments.get(identifier)
        attachments.append({"name": item["name"], "kind": item["kind"],
                            "content": base64.b64encode(read_blob(store.path.parent, item)).decode("ascii")})
    drafts = [Drafts(store).get(row[0])["data"] for row in store.db.execute("SELECT scope_key FROM composer_drafts ORDER BY scope_key")]
    return {"parameters": models.catalog.data["parameters"], "providers": models.catalog.data["providers"],
            "projects": store.list("project"), "sessions": store.list("session"), "messages": store.list("message"),
            "runs": store.runs(), "drafts": drafts, "attachments": sorted(attachments, key=lambda item: item["name"]),
            "attachment_files": sorted(path.name for path in store.attachments.directory.iterdir() if path.suffix in (".blob", ".txt")) if store.attachments.directory.exists() else [],
            "message_attachment_count": store.db.execute("SELECT count(*) FROM message_attachments").fetchone()[0],
            "grant_count": store.db.execute("SELECT count(*) FROM grants").fetchone()[0],
            "account_calls": len(account_calls), "provider_calls": len(provider_calls)}


async def serve(root, temperature):
    def reject_provider(_request):
        raise AssertionError("浏览器备份验收禁止模型请求")

    async with AsyncExitStack() as stack:
        source = await stack.enter_async_context(desktop(root / "source", handle=reject_provider))
        target = await stack.enter_async_context(desktop(root / "target", handle=reject_provider))
        await seed(source, root, temperature)
        mapped = root / "restored-project"
        mapped.mkdir()
        active = source
        emit({"ready": True, "root": str(root), "mapped_root": str(mapped), "source": snapshot(source)})
        while line := await asyncio.to_thread(sys.stdin.readline):
            message = json.loads(line)
            identifier = message["id"]
            try:
                command = message["command"]
                if command == "shutdown":
                    emit({"id": identifier, "result": {"closed": True}})
                    return
                if command == "target":
                    active = target
                    result = snapshot(active)
                elif command == "snapshot":
                    result = snapshot(active)
                elif command == "network":
                    result = {"account_calls": len(source[3]) + len(target[3]), "provider_calls": len(source[4]) + len(target[4])}
                elif command == "request":
                    request = message["request"]
                    response = await active[2].request(request["method"], request["path"],
                                                       headers=request.get("headers", {}), content=request.get("body") or None)
                    # body 只作为字符串穿过 IPC；绝不解析、重排或重新编码备份 JSON。
                    result = {"status": response.status_code, "headers": dict(response.headers), "body": response.text}
                else:
                    raise ValueError("未开放的备份验收命令")
                emit({"id": identifier, "result": result})
            except Exception as error:
                emit({"id": identifier, "error": f"{type(error).__name__}: {error}"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--temperature", type=float, choices=(0, 1, 0.7), required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    allowed = Path(__file__).resolve().parents[2] / ".run"
    if not root.is_relative_to(allowed.resolve()) or root == allowed.resolve():
        raise ValueError("备份验收目录必须是仓库 .run 内的独立目录")
    asyncio.run(serve(root, args.temperature))


if __name__ == "__main__":
    main()
