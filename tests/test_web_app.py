from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase
from omniquery_bot.rag_service import RagService
from omniquery_bot.vision_service import VisionService
from omniquery_bot.web_app import create_app


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
        if "hello" in prompt.lower():
            return self.schema(route="greeting", standalone_query="", reply="Hello! Ask about the docs or send an image.")
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
            caption="A plain blue square on a light background.",
            tags=["blue", "square", "minimal"],
        )


class FakeResponseModel:
    def invoke(self, messages, **kwargs):
        return FakeResponse("Use `py -3.11 -m venv .venv` to create the environment.")


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


def make_client(tmp_path: Path) -> TestClient:
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    (kb_dir / "python.md").write_text(
        "# Python FAQ\n\nUse `py -3.11 -m venv .venv` to create a virtual environment on Windows.",
        encoding="utf-8",
    )
    settings = make_settings(tmp_path, kb_dir)
    kb = FakeKnowledgeBase(settings)
    kb.setup()
    kb.reindex()
    models = FakeGateway()
    rag_service = RagService(settings, kb, models)
    vision_service = VisionService(settings, kb, models)
    app = create_app(settings=settings, kb=kb, rag_service=rag_service, vision_service=vision_service)
    return TestClient(app)


def test_chat_endpoint_returns_reply_and_sources(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/chat",
        json={"session_id": "local-test", "message": "How do I create a Python virtual environment?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "create the environment" in payload["reply"]
    assert payload["route"] == "rag"
    assert len(payload["sources"]) >= 1


def test_image_endpoint_returns_caption_and_tags(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    image = Image.new("RGB", (32, 32), color=(0, 0, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    response = client.post(
        "/api/image",
        data={"session_id": "local-test"},
        files={"file": ("blue-square.png", buffer.getvalue(), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["caption"].startswith("A plain blue square")
    assert payload["tags"] == ["blue", "square", "minimal"]


def test_history_endpoint_returns_chat_messages(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/api/chat",
        json={"session_id": "local-test", "message": "How do I create a Python virtual environment?"},
    )

    response = client.get("/api/history", params={"session_id": "local-test"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][1]["role"] == "assistant"


def test_config_endpoint_returns_runtime_config(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["text_model"] == "qwen3.5:4b"
    assert payload["embedding_model"] == "fake"
