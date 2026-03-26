from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from omniquery_bot.config import Settings
from omniquery_bot.llm_service import (
    GEMINI_DEFAULT_MAX_OUTPUT_TOKENS,
    OLLAMA_DEFAULT_MAX_OUTPUT_TOKENS,
    ModelGateway,
    coerce_text,
    _parse_image_payload,
    _structured_result_parts,
)


def test_chat_model_uses_low_reasoning_and_token_cap(tmp_path: Path) -> None:
    settings = Settings(
        project_root=tmp_path,
        telegram_bot_token="token",
        gemini_api_key="key",
        text_provider="ollama",
        vision_provider="ollama",
        ollama_base_url="http://localhost:11434",
        text_model="qwen3:4b",
        vision_model="qwen3.5:4b",
        gemini_model="gemini-2.5-flash",
        embedding_model="fake",
        db_path=tmp_path / "omniquerybot.db",
        kb_dir=tmp_path / "knowledge_base",
        top_k=3,
        history_window=3,
        min_relevance_score=0.4,
        chunk_size=700,
        chunk_overlap=100,
        source_snippet_count=2,
        source_snippet_length=180,
        rag_max_output_tokens=1024,
        image_max_edge=1600,
        log_level="INFO",
    )

    model = ModelGateway(settings).chat_model(temperature=0.2)

    assert model.reasoning == "low"
    assert model.num_predict == OLLAMA_DEFAULT_MAX_OUTPUT_TOKENS


def test_coerce_text_strips_leaked_thinking_content() -> None:
    raw = (
        "Reasoning that should not be shown.\n"
        "</think>\n\n"
        "Final answer to display."
    )

    assert coerce_text(raw) == "Final answer to display."


def test_chat_model_supports_gemini_provider(tmp_path: Path) -> None:
    settings = Settings(
        project_root=tmp_path,
        telegram_bot_token="token",
        gemini_api_key="key",
        text_provider="gemini",
        vision_provider="ollama",
        ollama_base_url="http://localhost:11434",
        text_model="gemini-2.5-flash",
        vision_model="qwen3:4b",
        gemini_model="gemini-2.5-flash",
        embedding_model="fake",
        db_path=tmp_path / "omniquerybot.db",
        kb_dir=tmp_path / "knowledge_base",
        top_k=3,
        history_window=3,
        min_relevance_score=0.4,
        chunk_size=700,
        chunk_overlap=100,
        source_snippet_count=2,
        source_snippet_length=180,
        rag_max_output_tokens=1024,
        image_max_edge=1600,
        log_level="INFO",
    )

    model = ModelGateway(settings).chat_model(temperature=0.0)

    assert hasattr(model, "invoke")
    assert model.model_name == "gemini-2.5-flash"
    assert model.max_output_tokens == GEMINI_DEFAULT_MAX_OUTPUT_TOKENS


def test_parse_image_payload_accepts_python_style_dict() -> None:
    payload = _parse_image_payload(
        "{'caption': 'A cat on a sofa.', 'tags': ['cat', 'sofa', 'indoor']}"
    )

    assert payload["caption"] == "A cat on a sofa."
    assert payload["tags"] == ["cat", "sofa", "indoor"]


def test_parse_image_payload_accepts_caption_and_tags_lines() -> None:
    payload = _parse_image_payload(
        "Caption: A green square on a plain background.\n"
        "Tags: green, square, minimal"
    )

    assert payload["caption"] == "A green square on a plain background."
    assert payload["tags"] == ["green", "square", "minimal"]


class _ImageResponse(BaseModel):
    caption: str
    tags: list[str]


class _FakeRawMessage:
    def __init__(self, content):
        self.content = content


def test_structured_result_parts_extracts_raw_and_parsed_payload() -> None:
    parsed, raw_text, parsing_error = _structured_result_parts(
        {
            "parsed": _ImageResponse(caption="A cat on a sofa.", tags=["cat", "sofa", "indoor"]),
            "raw": _FakeRawMessage(
                [
                    {
                        "text": '{"caption":"A cat on a sofa.","tags":["cat","sofa","indoor"]}',
                    }
                ]
            ),
            "parsing_error": None,
        }
    )

    assert parsed.caption == "A cat on a sofa."
    assert raw_text == '{"caption":"A cat on a sofa.","tags":["cat","sofa","indoor"]}'
    assert parsing_error is None
