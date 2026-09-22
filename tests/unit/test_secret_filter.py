"""秘密过滤使用合成值验证，覆盖逐字符流及原始数据不变性。"""
import copy
import json

import pytest

from private_agent_local.secret_filter import MAX_STREAM_LINE, REDACTED, SecretFilter

KEY = "fixture-private-key-928173"


@pytest.mark.parametrize("text", [
    f"前缀 {KEY} 后缀", "Authorization: Bearer abcdef-secret", '"api_key": "quoted secret value"',
    "password=secret-value; next", "https://user:private-password@example.test/path",
    "postgres://user:private-password@example.test/database",
    "sk-proj-abcdefghijklmnopqrstuvwxyz123456", "ghp_abcdefghijklmnopqrstuvwxyz123456",
    "-----BEGIN PRIVATE KEY-----\nsynthetic-private-body\n-----END PRIVATE KEY-----", "token=边界测试令牌",
])
def test_stream_all_split_positions_match_complete_redaction(text):
    secret_filter = SecretFilter(lambda: (KEY,))
    expected = secret_filter.redact_text(text)
    assert expected != text
    for index in range(len(text) + 1):
        stream = secret_filter.stream()
        result = stream.feed(text[:index]) + stream.feed(text[index:]) + stream.finish()
        assert result == expected, (index, text, result, expected)
    stream = secret_filter.stream()
    assert "".join(stream.feed(character) for character in text) + stream.finish() == expected


def test_stream_releases_normal_unicode_without_newline_and_closes_idempotently():
    stream = SecretFilter(lambda: ("account-a", KEY)).stream()
    assert stream.feed("检查文件🙂") == "检查文件🙂"
    assert stream.feed("完成。") == "完成。"
    assert stream.finish() == stream.finish() == ""
    with pytest.raises(ValueError, match="已关闭"):
        stream.feed("late")


def test_recursive_redaction_is_a_copy_and_does_not_change_files(tmp_path):
    original = {"content": f"配置 {KEY}", "nested": [{"password": "another value"}, {"count": 3}], "token_count": 123}
    snapshot = copy.deepcopy(original)
    target = tmp_path / "source.txt"
    target.write_text(original["content"], encoding="utf-8")
    secret_filter = SecretFilter(lambda: (KEY, ""))
    result = secret_filter.redact_value(original)
    assert result["content"] == f"配置 {REDACTED}"
    assert result["nested"][0]["password"] == REDACTED
    assert result["nested"][1] == {"count": 3} and result["token_count"] == 123
    assert original == snapshot
    assert target.read_text(encoding="utf-8") == original["content"]
    assert secret_filter.contains_secret(original)
    assert not secret_filter.contains_secret(result)


def test_stream_tracks_rotated_credentials_and_masks_cancelled_prefix():
    values = [KEY]
    secret_filter = SecretFilter(lambda: values)
    stream = secret_filter.stream()
    assert stream.feed(KEY[:10]) == ""
    values.clear()
    assert stream.feed(KEY[10:]) + stream.finish() == REDACTED
    values.append(KEY)
    stream = secret_filter.stream()
    assert stream.feed("安全文本 " + KEY[:12]) == "安全文本 "
    assert stream.finish() == REDACTED


def test_stream_bounds_unfinished_value_and_resumes_after_newline():
    stream = SecretFilter().stream()
    assert stream.feed("token=" + "a" * (MAX_STREAM_LINE + 1)) == REDACTED
    assert stream.feed("still-secret") == ""
    assert stream.feed("\n下一条正常消息") == "\n下一条正常消息"
    assert stream.finish() == ""


def test_long_private_key_remains_masked_until_split_end_marker():
    stream = SecretFilter().stream()
    assert stream.feed("-----BEGIN PRIVATE KEY-----\n" + "a" * MAX_STREAM_LINE) == REDACTED
    assert stream.feed("\nmore-body\n-----END PRIVATE ") == ""
    assert stream.feed("KEY-----\n完成") == "\n完成"
    assert stream.finish() == ""


def test_empty_values_and_nonsecret_identifiers_are_preserved():
    secret_filter = SecretFilter(lambda: ("",))
    value = {"api_key": "", "token_count": 42, "secret": {"type": "string"}, "content": "token_count=42"}
    assert secret_filter.redact_value(value) == value
    assert not secret_filter.contains_secret(value)


def test_known_secret_gate_keeps_code_annotations_and_environment_lookups():
    secret_filter = SecretFilter(lambda: (KEY,))
    for text in ('password: str', 'token = os.getenv("TOKEN")', 'password = get_password()', 'token: string'):
        assert not secret_filter.contains_known_secret(text)
        assert secret_filter.redact_text(text) == text
    assert secret_filter.contains_known_secret({"parts": [KEY]})


def test_sensitive_object_keys_are_filtered_without_collision_or_mutation():
    original = {KEY: "first", "fixture-second-private": "second", REDACTED: "third"}
    secret_filter = SecretFilter(lambda: (KEY, "fixture-second-private"))
    result = secret_filter.redact_value(original)
    assert len(result) == len(original)
    assert set(result.values()) == {"first", "second", "third"}
    assert not secret_filter.contains_known_secret(result)
    assert original[KEY] == "first"


@pytest.mark.parametrize("kind", ["commentary", "summary", "arguments"])
def test_provider_public_state_detects_secrets_outside_final_text(kind):
    secret_filter = SecretFilter(lambda: (KEY,))
    public_item = {
        "commentary": {"type": "message", "phase": "commentary", "content": [{"type": "output_text", "text": KEY}]},
        "summary": {"type": "reasoning", "encrypted_content": "opaque", "summary": [{"type": "summary_text", "text": KEY}]},
        "arguments": {"type": "function_call", "arguments": json.dumps({"text": KEY})},
    }[kind]
    raw = json.dumps([public_item, {"type": "message", "phase": "final_answer", "content": [{"type": "output_text", "text": "完成"}]}])
    assert secret_filter.contains_public_provider_secret(raw)
    assert not secret_filter.contains_public_provider_secret(secret_filter.redact_provider_output(raw))


def test_provider_state_keeps_opaque_encrypted_content_and_rejects_malformed():
    secret_filter = SecretFilter(lambda: (KEY,))
    raw = json.dumps([{"type": "reasoning", "encrypted_content": KEY, "summary": []}])
    assert not secret_filter.contains_public_provider_secret(raw)
    assert json.loads(secret_filter.redact_provider_output(raw))[0]["encrypted_content"] == KEY
    assert secret_filter.contains_public_provider_secret("invalid json")
    assert secret_filter.contains_public_provider_secret(json.dumps([{"type": "message", "id": KEY, "content": []}]))
    assert secret_filter.contains_public_provider_secret(json.dumps([{"type": "message", "content": [{"text": KEY[:10]}, {"text": KEY[10:]}]}]))


def test_clean_provider_state_and_native_argument_strings_remain_byte_identical():
    arguments = '{"rel_path":"中文.py","start_line":1}'
    items = [{"type": "reasoning", "encrypted_content": "opaque", "summary": []},
             {"type": "function_call", "arguments": arguments}]
    raw = json.dumps(items, ensure_ascii=True, indent=3) + "\n"
    secret_filter = SecretFilter(lambda: (KEY,))
    assert secret_filter.redact_provider_output(raw) == raw
    items.insert(1, {"type": "message", "content": [{"text": KEY}]})
    filtered = json.loads(secret_filter.redact_provider_output(json.dumps(items)))
    assert filtered[-1]["arguments"] == arguments
    assert filtered[1]["content"][0]["text"] == REDACTED


@pytest.mark.parametrize("text,expected", [
    ("把词法分析代码改成 token=next_token，并解释 token 的含义。", "把词法分析代码改成 token=next_token，并解释 token 的含义。"),
    ("代码表达式：`token = lexer.current`。继续修复", "代码表达式：`token = lexer.current`。继续修复"),
    ("token=opaque_value，请保留后面的要求。", "token=[REDACTED]，请保留后面的要求。"),
    ("password=synthetic-value。修复 A.py；运行测试", "password=[REDACTED]。修复 A.py；运行测试"),
    (f"代码表达式 token={KEY}，继续解释", "代码表达式 token=[REDACTED]，继续解释"),
    ('代码：token="fixture literal"，继续解释', '代码：token="[REDACTED]"，继续解释'),
    ("代码连接失败，token=opaque_value。请检查", "代码连接失败，token=[REDACTED]。请检查"),
    ("代码需要 token=opaque_value", "代码需要 token=[REDACTED]"),
])
def test_code_context_and_chinese_boundaries_match_every_stream_split(text, expected):
    filtering = SecretFilter(lambda: (KEY,))
    assert filtering.redact_text(text) == expected
    for split in range(len(text) + 1):
        stream = filtering.stream()
        assert stream.feed(text[:split]) + stream.feed(text[split:]) + stream.finish() == expected
    stream = filtering.stream()
    assert "".join(stream.feed(char) for char in text) + stream.finish() == expected


def test_stream_retains_code_fence_context_after_bounded_history_rolls_over():
    text = "```python\n" + "# ordinary code\n" * 90 + "token=next_token\n```\ntoken=opaque_value。继续"
    filtering = SecretFilter()
    expected = text.replace("token=opaque_value", "token=" + REDACTED)
    assert filtering.redact_text(text) == expected
    stream = filtering.stream()
    assert "".join(stream.feed(char) for char in text) + stream.finish() == expected
