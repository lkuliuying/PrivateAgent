"""应用数据目录边界测试。"""
from __future__ import annotations

from personal_assistant.api.routes_activities import _upload_path as activity_upload_path
from personal_assistant.api.routes_documents import _upload_path as document_upload_path
from personal_assistant.config import settings
from personal_assistant.core.tools import _tool_upload_path


def test_upload_helpers_follow_configured_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    expected = tmp_path / "uploads" / "42.md"
    assert document_upload_path(42, "note.md") == expected
    assert activity_upload_path(42, "note.md") == expected
    assert _tool_upload_path(42, "note.md") == expected
    assert expected.parent.is_dir()
