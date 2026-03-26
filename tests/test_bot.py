from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from omniquery_bot.bot import format_rag_message, help_text
from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase
from omniquery_bot.llm_service import GenerationError
from omniquery_bot.rag_service import RagService, _extractive_fallback_answer, _should_use_extractive_fallback
from omniquery_bot.vision_service import VisionService


class FakeKnowledgeBase(KnowledgeBase):
    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    def _embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "python" in lowered or "virtual" in lowered:
            return [1.0, 0.0, 0.0]
        if "docker" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeStructuredModel:
    def __init__(self, schema) -> None:
        self.schema = schema

    def invoke(self, messages, **kwargs):
        prompt = "\n".join(str(message.content) for message in messages)
        if "hello there" in prompt.lower():
            return self.schema(route="greeting", standalone_query="", reply="Hello! Ask me about the stored docs.")
        if "what about docker?" in prompt.lower():
            return self.schema(
                route="rag",
                standalone_query="What do the knowledge base documents say about Docker basics?",
                reply="",
            )
        return self.schema(
            route="rag",
            standalone_query="How do I create a Python virtual environment?",
            reply="",
        )


class FakeGateway:
    def structured_chat_model(self, schema, temperature: float = 0.0):
        return FakeStructuredModel(schema)

    def chat_model(self, temperature: float = 0.2, *, reasoning="low", num_predict=None):
        return FakeResponseModel()

    def describe_image(self, image_bytes, mime_type, schema, instruction):
        return schema(
            caption="A simple green square on a plain background.",
            tags=["green", "square", "minimal"],
        )


class FakeResponseModel:
    def invoke(self, messages, **kwargs):
        prompt = "\n".join(str(message.content) for message in messages)
        if "docker basics" in prompt.lower():
            return FakeResponse("Docker packages the app and its dependencies into a portable container.")
        return FakeResponse("Use `py -3.11 -m venv .venv` to create a virtual environment.")


def make_settings(tmp_path: Path, kb_dir: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        telegram_bot_token="token",
        gemini_api_key="key",
        text_provider="ollama",
        vision_provider="ollama",
        ollama_base_url="http://localhost:11434",
        text_model="qwen3.5:4b",
        vision_model="qwen3.5:4b",
        gemini_model="gemini-2.5-flash",
        embedding_model="fake",
        db_path=tmp_path / "omniquerybot.db",
        kb_dir=kb_dir,
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


def make_services(tmp_path: Path) -> tuple[Settings, FakeKnowledgeBase, RagService, VisionService]:
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    (kb_dir / "python.md").write_text(
        "# Python FAQ\n\nUse `py -3.11 -m venv .venv` to create a virtual environment on Windows.",
        encoding="utf-8",
    )
    (kb_dir / "docker.md").write_text(
        "# Docker Basics\n\nDocker packages the app and its dependencies into a portable container.",
        encoding="utf-8",
    )
    settings = make_settings(tmp_path, kb_dir)
    kb = FakeKnowledgeBase(settings)
    kb.setup()
    kb.reindex()
    models = FakeGateway()
    return settings, kb, RagService(settings, kb, models), VisionService(settings, kb, models)


def test_rag_service_saves_rewritten_query_and_sources(tmp_path: Path) -> None:
    settings, kb, rag_service, _vision_service = make_services(tmp_path)
    result = rag_service.answer("user-1", "How do I create a Python virtual environment?")
    turns = kb.recent_turns("user-1", 5)
    formatted = format_rag_message(result.reply, result.sources, settings)

    assert "virtual environment" in result.reply.lower()
    assert result.rewritten_query.startswith("How do I create a Python")
    assert len(turns) == 1
    assert turns[0]["rewritten_query"].startswith("How do I create a Python")
    assert formatted.count("Sources:") == 1
    assert "knowledge_base/python.md" in formatted.replace("\\", "/")


def test_rag_service_answers_greeting_without_retrieval(tmp_path: Path) -> None:
    _settings, kb, rag_service, _vision_service = make_services(tmp_path)
    result = rag_service.answer("user-1", "hello there")
    turns = kb.recent_turns("user-1", 5)

    assert result.route == "greeting"
    assert result.sources == []
    assert turns[0]["mode"] == "greeting"


def test_vision_service_stores_image_turn(tmp_path: Path) -> None:
    _settings, kb, _rag_service, vision_service = make_services(tmp_path)
    image = Image.new("RGB", (40, 40), color=(0, 255, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    result = vision_service.describe("user-2", buffer.getvalue(), "image/png", "green-square.png")
    turns = kb.recent_turns("user-2", 5)

    assert result.caption.startswith("A simple green square")
    assert result.tags == ["green", "square", "minimal"]
    assert turns[0]["caption"].startswith("A simple green square")
    assert kb.is_waiting_for_image("user-2") is False


def test_help_text_lists_required_commands() -> None:
    text = help_text()
    assert "/help" in text
    assert "/ask" in text
    assert "/image" in text
    assert "3 tags" in text


class RecordingStructuredModel:
    def __init__(self, schema) -> None:
        self.schema = schema
        self.calls: list[dict] = []

    def invoke(self, messages, **kwargs):
        self.calls.append(kwargs)
        return self.schema(
            route="rag",
            standalone_query="What do the knowledge base documents say about Docker basics?",
            reply="",
        )


class RecordingResponseModel:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke(self, messages, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse("Docker packages the app and its dependencies into a portable container.")


class RecordingGateway:
    def __init__(self) -> None:
        self.rewrite_model = RecordingStructuredModel(None)
        self.answer_model = RecordingResponseModel()
        self.chat_model_calls: list[dict] = []

    def structured_chat_model(self, schema, temperature: float = 0.0):
        self.rewrite_model.schema = schema
        return self.rewrite_model

    def chat_model(self, temperature: float = 0.2, *, reasoning="low", num_predict=None):
        self.chat_model_calls.append(
            {
                "temperature": temperature,
                "reasoning": reasoning,
                "num_predict": num_predict,
            }
        )
        return self.answer_model


def test_rag_service_disables_streaming_for_rewrite_and_answer(tmp_path: Path) -> None:
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    (kb_dir / "docker.md").write_text(
        "# Docker Basics\n\nDocker packages the app and its dependencies into a portable container.",
        encoding="utf-8",
    )
    settings = make_settings(tmp_path, kb_dir)
    kb = FakeKnowledgeBase(settings)
    kb.setup()
    kb.reindex()
    gateway = RecordingGateway()
    rag_service = RagService(settings, kb, gateway)

    kb.add_turn(
        "user-3",
        "ask",
        {
            "mode": "rag",
            "user_message": "Tell me about Python.",
            "rewritten_query": "Tell me about Python.",
            "assistant_message": "Python is in the docs.",
            "sources": [],
        },
    )

    rag_service.answer("user-3", "What about Docker?")

    assert gateway.rewrite_model.calls == [{"stream": False}]
    assert gateway.chat_model_calls == [
        {
            "temperature": 0.0,
            "reasoning": "low",
            "num_predict": settings.rag_max_output_tokens,
        }
    ]
    assert gateway.answer_model.calls == [{"stream": False}]


def test_extractive_fallback_prefers_instructional_source() -> None:
    reply = _extractive_fallback_answer(
        "How do I create a Python virtual environment?",
        [
            {
                "heading": "Why use a virtual environment?",
                "text": "Why use a virtual environment? It keeps dependencies isolated.",
                "score": 0.95,
            },
            {
                "heading": "How do I create a virtual environment on Windows?",
                "text": "Use `py -3.11 -m venv .venv` from the project root. Then activate it with `.\\.venv\\Scripts\\activate`.",
                "score": 0.8,
            },
        ],
    )

    assert "py -3.11 -m venv .venv" in reply


def test_quality_guard_falls_back_for_short_literal_missing_answer() -> None:
    should_fallback = _should_use_extractive_fallback(
        "How do I create the environment on Windows?",
        "Install Python",
        [
            {
                "heading": "How do I create a virtual environment on Windows?",
                "text": "Use `py -3.11 -m venv .venv` from the project root. Then activate it with `.\\.venv\\Scripts\\activate`.",
                "score": 0.9,
            }
        ],
        {"done_reason": "FinishReason.MAX_TOKENS"},
    )

    assert should_fallback is True


class FailingResponseModel:
    def invoke(self, messages, **kwargs):
        raise GenerationError("provider unavailable")


class FailingAnswerGateway(FakeGateway):
    def chat_model(self, temperature: float = 0.2, *, reasoning="low", num_predict=None):
        return FailingResponseModel()


def test_rag_service_falls_back_when_provider_generation_fails(tmp_path: Path) -> None:
    settings, kb, _rag_service, _vision_service = make_services(tmp_path)
    rag_service = RagService(settings, kb, FailingAnswerGateway())

    result = rag_service.answer("user-5", "How do I create a Python virtual environment?")

    assert "py -3.11 -m venv .venv" in result.reply
