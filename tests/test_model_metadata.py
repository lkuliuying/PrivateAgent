from __future__ import annotations

from personal_assistant.core.model_metadata import (
    discover_model_metadata,
    ollama_show_metadata,
)


def test_discovers_common_provider_context_fields() -> None:
    openrouter = discover_model_metadata(
        {
            "data": [
                {
                    "id": "vendor/model-a",
                    "context_length": 262_144,
                    "top_provider": {"max_completion_tokens": 16_384},
                }
            ]
        },
        base_url="https://openrouter.ai/api/v1",
        protocol="openai",
    )[0]
    assert openrouter.context_tokens == 262_144
    assert openrouter.max_output_tokens == 16_384
    assert openrouter.metadata_source == "provider_api"

    gemini = discover_model_metadata(
        {
            "models": [
                {
                    "name": "models/gemini-test",
                    "inputTokenLimit": 1_048_576,
                    "outputTokenLimit": 65_536,
                }
            ]
        },
        base_url="https://generativelanguage.googleapis.com/v1beta",
        protocol="openai",
    )[0]
    assert gemini.context_tokens == 1_048_576
    assert gemini.max_output_tokens == 65_536


def test_deepseek_catalog_and_unknown_do_not_fall_back_to_32k() -> None:
    models = discover_model_metadata(
        {
            "data": [
                {"id": "deepseek-v4-flash"},
                {"id": "deepseek-v4-flash-vision-exp"},
            ]
        },
        base_url="https://api.deepseek.com",
        protocol="openai",
    )
    found = {model.model_id: model for model in models}
    assert found["deepseek-v4-flash"].context_tokens == 1_000_000
    assert found["deepseek-v4-flash"].metadata_source == "official_catalog"
    assert found["deepseek-v4-flash-vision-exp"].context_tokens is None
    assert found["deepseek-v4-flash-vision-exp"].metadata_source == "unknown"


def test_ollama_show_reads_architecture_context_length() -> None:
    metadata = ollama_show_metadata(
        "qwen-local",
        {
            "model_info": {
                "general.architecture": "qwen2",
                "qwen2.context_length": 131_072,
            }
        },
    )
    assert metadata is not None
    assert metadata.context_tokens == 131_072
    assert metadata.metadata_source == "local_model"
