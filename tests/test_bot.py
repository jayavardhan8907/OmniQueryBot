from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from omniquery_bot.bot import answer_image, answer_query, summarize_last
from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase


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
        return "Use `py -3.11 -m venv .venv` to create a virtual environment."

    def describe_image(self, image_bytes, mime_type):
        return {"caption": "A simple green square on a plain background.", "tags": ["green", "square", "minimal"]}

    def summarize(self, artifact_type, artifact_text):
        return f"Summary for {artifact_type}: {artifact_text[:40]}"


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


def make_kb(tmp_path: Path) -> tuple[Settings, FakeKnowledgeBase]:
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
    return settings, kb


def test_answer_query_saves_history_and_sources(tmp_path: Path) -> None:
    settings, kb = make_kb(tmp_path)
    message = answer_query(settings, kb, FakeGemini(), "user-1", "How do I create a Python virtual environment?")
    turns = kb.recent_turns("user-1", 5)

    assert "virtual environment" in message.lower()
    assert "Sources:" in message
    assert len(turns) == 1
    assert turns[0]["kind"] == "ask"


def test_answer_image_and_summarize_flow(tmp_path: Path) -> None:
    settings, kb = make_kb(tmp_path)
    kb.set_waiting_for_image("user-2", True)

    image = Image.new("RGB", (40, 40), color=(0, 255, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    image_message = answer_image(
        settings,
        kb,
        FakeGemini(),
        "user-2",
        buffer.getvalue(),
        "image/png",
        "green-square.png",
    )
    summary = summarize_last(kb, FakeGemini(), "user-2")
    state = kb.user_state("user-2")

    assert "Caption:" in image_message
    assert summary is not None
    assert summary.startswith("Summary for image:")
    assert state["waiting_for_image"] is False
