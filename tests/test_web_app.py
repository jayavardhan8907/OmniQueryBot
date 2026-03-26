from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase
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


class FakeGemini:
    def answer_with_context(self, query, sources, history):
        return "Use `py -3.11 -m venv .venv` to create the environment."

    def describe_image(self, image_bytes, mime_type):
        return {
            "caption": "A plain blue square on a light background.",
            "tags": ["blue", "square", "minimal"],
        }

    def summarize(self, artifact_type, artifact_text):
        return f"Summary for {artifact_type}: {artifact_text[:48]}"


def make_settings(tmp_path: Path, kb_dir: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        telegram_bot_token="token",
        gemini_api_key="key",
        genai_model="gemini-2.5-flash",
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
    app = create_app(settings=settings, kb=kb, gemini=FakeGemini())
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


def test_summarize_endpoint_uses_last_artifact(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/api/chat",
        json={"session_id": "local-test", "message": "How do I create a Python virtual environment?"},
    )

    response = client.post("/api/summarize", json={"session_id": "local-test"})

    assert response.status_code == 200
    assert response.json()["reply"].startswith("Summary for ask:")
