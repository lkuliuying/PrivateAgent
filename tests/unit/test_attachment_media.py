"""图片/PDF 的真实本机解码、模型协议与持久化回归，使用合成材料。"""
import io
import json
import uuid

import pytest
from PIL import Image
from test_local_attachments import (
    AUTHORITY,
    NoSecrets,
    commit_attachment,
    fixture_store,
)
from test_local_executor import TERMINAL, call, close, response, setup, until

from private_agent_core.context import request_budget
from private_agent_core.contracts import ModelImage, ModelMessage, ModelRequest
from private_agent_core.history import TEXT_FIELDS, TEXT_FORMAT, validate_archive
from private_agent_core.llm.adapters import (
    _claude_messages,
    _ollama_messages,
    _openai_messages,
)
from private_agent_core.llm.responses import OpenAIResponsesAdapter
from private_agent_local import attachment_media as media
from private_agent_local.attachment_context import with_attachment_images
from private_agent_local.attachments import read_blob
from private_agent_local.migration import (
    apply_history,
    archive_sqlite,
    preview_history,
    rollback_history,
)
from private_agent_local.model_errors import CloudError


def image_bytes(format="PNG", size=(40, 30)):
    with Image.new("RGB", size, "white") as image:
        output = io.BytesIO()
        image.save(output, format=format)
        return output.getvalue()


def text_pdf():
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    text = b"BT /F1 12 Tf 10 40 Td (Local PDF fixture) Tj ET"
    objects.append(b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream")
    result, offsets = b"%PDF-1.4\n", []
    for index, body in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    offset = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n"
    result += b"".join(f"{value:010d} 00000 n \n".encode() for value in offsets)
    return result + f"trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n{offset}\n%%EOF\n".encode()


def stage(tmp_path, store, pid, wid, raw, name):
    source = tmp_path / name
    source.write_bytes(raw)
    draft = uuid.uuid4().hex
    return store.attachments.stage(source, draft, pid, wid, None, secret_filter=NoSecrets()), draft, source


@pytest.mark.parametrize("suffix,format", [("png", "PNG"), ("jpg", "JPEG"), ("webp", "WEBP")])
def test_image_snapshot_scope_and_restart(tmp_path, suffix, format):
    store, pid, wid, session = fixture_store(tmp_path)
    raw = image_bytes(format)
    item, draft, source = stage(tmp_path, store, pid, wid, raw, "picture." + suffix)
    try:
        assert item["kind"] == "image" and item["requires_vision"]
        with pytest.raises(ValueError, match="未提交"):
            store.attachments.image(item["id"], session_id=session["id"])
        preview = store.attachments.image(item["id"], draft_id=draft)
        assert preview["mime_type"] == "image/jpeg"
        source.write_bytes(b"changed after selection")
        assert read_blob(store.path.parent, item) == raw
        commit_attachment(store, item, draft, session)
        path = store.path
        store.db.close()
        from private_agent_local.store import Store
        store = Store(path)
        assert store.attachments.image(item["id"], session_id=session["id"]) == preview
        with pytest.raises(ValueError, match="未提交"):
            store.attachments.image(item["id"], session_id=session["id"] + 1)
    finally:
        store.db.close()


def test_pdf_text_and_scan_pages_are_bounded(tmp_path):
    metadata, text = media.inspect(text_pdf(), "sample.pdf")
    assert text.strip() == "Local PDF fixture" and not metadata["requires_vision"]
    assert media.text_page(text_pdf(), 1).strip() == text.strip()
    scan = image_bytes("PDF")
    metadata, text = media.inspect(scan, "scan.pdf")
    assert metadata["scan_pages"] == [1] and not text.strip()
    image = media.render(scan, {**metadata, "name": "scan.pdf"}, 1)
    assert image["width"] <= 1536 and image["height"] <= 1536
    with pytest.raises(ValueError, match="页码"):
        media.text_page(scan, 2)
    with Image.new("RGB", (1, 1)) as page:
        output = io.BytesIO()
        page.save(output, format="PDF", save_all=True, append_images=[page] * 50)
        with pytest.raises(ValueError, match="50 页"):
            media.inspect(output.getvalue(), "too-many.pdf")


@pytest.mark.parametrize("name,raw", [
    ("empty.png", b""), ("bad.pdf", b"%PDF-1.4 invalid"), ("spoof.png", b"%PDF-1.4 invalid"),
    ("large.pdf", b"x" * (10 * 1024 * 1024 + 1)), ("binary.txt", b"\0"),
], ids=["empty-image", "damaged-pdf", "spoofed-image", "over-size", "binary-text"])
def test_invalid_media_does_not_leave_snapshots(tmp_path, name, raw):
    store, pid, wid, _ = fixture_store(tmp_path)
    try:
        with pytest.raises((ValueError, UnicodeError)):
            stage(tmp_path, store, pid, wid, raw, name)
        assert store.db.execute("SELECT count(*) FROM task_attachments").fetchone()[0] == 0
        assert not list(store.attachments.directory.glob("*"))
    finally:
        store.db.close()


def test_dimensions_animation_and_pdf_credentials_are_checked(tmp_path):
    with pytest.raises(ValueError, match="像素"):
        media.inspect(image_bytes(size=(16385, 1)), "large.png")
    with Image.new("RGB", (2, 2), "white") as first, Image.new("RGB", (2, 2), "black") as second:
        output = io.BytesIO()
        first.save(output, format="PNG", save_all=True, append_images=[second])
        with pytest.raises(ValueError, match="动画"):
            media.inspect(output.getvalue(), "animated.png")
    class Filter:
        def contains_secret(self, text):
            return "Local PDF fixture" in text
    store, pid, wid, _ = fixture_store(tmp_path)
    try:
        with pytest.raises(ValueError, match="疑似凭据"):
            with store.transaction():
                store.attachments.install_bytes("sample.pdf", text_pdf(), pid, wid, secret_filter=Filter())
        assert not list(store.attachments.directory.glob("*"))
    finally:
        store.db.close()


def test_v3_binary_roundtrip_rollback_and_v2_compatibility(tmp_path):
    store, pid, wid, session = fixture_store(tmp_path)
    item, draft, _ = stage(tmp_path, store, pid, wid, image_bytes(), "sample.png")
    commit_attachment(store, item, draft, session)
    target, _, _, _ = fixture_store(tmp_path, "target")
    try:
        archive = archive_sqlite(store.path, authority=AUTHORITY, owner_id=1)
        assert archive["format"] == "privateagent.history.v3"
        row = archive["records"]["attachments"][0]
        assert row["content_encoding"] == "base64"
        damaged = json.loads(json.dumps(archive))
        damaged["records"]["attachments"][0]["sha256"] = "0" * 64
        with pytest.raises(ValueError, match="摘要"):
            validate_archive(damaged, authority=AUTHORITY, owner_id=1)
        path = tmp_path / "media.json"
        path.write_text(json.dumps(archive), encoding="utf-8")
        preview = preview_history(str(path), authority=AUTHORITY, owner_id=1)
        destination_root = tmp_path / "imported-project"
        destination_root.mkdir()
        # 导入重新创建项目记录，授权不会恢复。
        result = apply_history(target, str(path), preview["sha256"], {str(pid): str(destination_root)}, authority=AUTHORITY, owner_id=1)
        restored = target.attachments.get(target.db.execute("SELECT id FROM task_attachments").fetchone()[0])
        assert restored["id"] != item["id"] and read_blob(target.path.parent, restored) == image_bytes()
        rollback_history(target, result["id"])
        assert not list(target.attachments.directory.glob("*.blob"))
        legacy = {**archive, "format": TEXT_FORMAT, "records": {key: [] for key in TEXT_FIELDS}}
        validate_archive(legacy, authority=AUTHORITY, owner_id=1)
    finally:
        store.db.close()
        target.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,format", [("sample.png", "PNG"), ("scan.pdf", "PDF")])
async def test_visual_model_flow_and_no_project_changes(tmp_path, name, format):
    app, client, server, root, body = await setup(tmp_path)
    owner = app.state.desktop.runtime
    try:
        item, draft, _ = stage(tmp_path, owner.store, body["project_id"], body["workspace_id"], image_bytes(format), name)
        assert not list(root.iterdir())
        preview = await client.get(f"/task-attachments/{item['id']}/content", params={"draft_id": draft})
        assert preview.status_code == 200 and preview.json()["image_data_url"].startswith("data:image/jpeg;base64,")
        request = {**body, "permission_mode": "readonly", "attachment_ids": [item["id"]], "attachment_draft_id": draft, "client_request_id": "visual-once"}
        rejected = await client.post("/agent-runs", json=request)
        assert rejected.status_code == 422 and rejected.json()["error_code"] == "model_vision_unsupported"
        assert owner.store.attachments.list_draft(draft)
        assert not owner.store.list("message")
        server.profiles[0]["supports_vision"] = True
        server.responses = [response(call("read_task_attachment", {"attachment_id": item["id"]})), response(text="已查看合成测试图片")]
        result = await client.post("/agent-runs", json=request)
        assert result.status_code == 201, result.text
        await until(client, result.json()["id"], TERMINAL)
        calls = [json.loads(raw)["request"] for path, raw in server.calls if path.endswith("complete")]
        assert not any(message.get("images") for message in calls[0]["messages"])
        visuals = [message for message in calls[1]["messages"] if message.get("images")]
        assert len(visuals) == 1
        encoded = visuals[0]["images"][0]["data"]
        assert encoded not in json.dumps(owner.store.context.items(body["session_id"]), ensure_ascii=False)
        assert (await client.post("/agent-runs", json=request)).json()["id"] == result.json()["id"]
        args = {"session_id": body["session_id"], "rel_path": "import." + name.rsplit(".", 1)[1]}
        assert (await client.post(f"/task-attachments/{item['id']}/import", json=args)).status_code == 200
        assert (root / args["rel_path"]).read_bytes() == read_blob(owner.store.path.parent, item)
        assert (await client.post(f"/task-attachments/{item['id']}/import", json=args)).status_code == 422
        with pytest.raises(CloudError, match="缺失或损坏"):
            with_attachment_images((ModelMessage(role="tool", name="read_task_attachment", tool_call_id="fixture",
                content=json.dumps({"success": True, "output": {"image_ref": {"attachment_id": item["id"], "page": 1}}})),),
                owner.store.attachments, body["session_id"] + 1, supports_vision=True)
    finally:
        await close(app, client)


def test_all_four_protocols_send_inline_images_and_budget_excludes_base64():
    image = ModelImage(**media.render(image_bytes(), {"kind": "image", "name": "fixture.png"}))
    request = ModelRequest(messages=(ModelMessage(role="user", content="只读图片材料", images=(image,)),))
    data_url = "data:image/jpeg;base64," + image.data
    assert _openai_messages(request.messages)[0]["content"][1]["image_url"]["url"] == data_url
    assert _ollama_messages(request.messages)[0]["images"] == [image.data]
    assert _claude_messages(request.messages)[1][0]["content"][1]["source"]["data"] == image.data
    adapter = OpenAIResponsesAdapter(base_url="https://fixture.test/v1", model="vision", api_key="synthetic-key")
    assert adapter._input(request)[0]["content"][1]["image_url"] == data_url
    budget = request_budget(request, 32000, 2048)
    assert 8192 < budget["estimated_input_tokens"] < 12000
    assert not budget["exceeded"]
    with pytest.raises(ValueError):
        ModelMessage(role="system", images=(image,))
    with pytest.raises(ValueError):
        ModelImage(mime_type="image/jpeg", data="not base64", width=1, height=1)
