from __future__ import annotations

from pathlib import Path

import numpy as np

from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase


class FakeKnowledgeBase(KnowledgeBase):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.query_calls = 0

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed_query(self, query: str) -> list[float]:
        self.query_calls += 1
        return self._embed(query)

    def _embed(self, text: str) -> list[float]:
        lowered = text.lower()
        vector = np.array(
            [
                lowered.count("python"),
                lowered.count("virtual"),
                lowered.count("environment"),
                lowered.count("docker"),
                lowered.count("api"),
                1.0,
            ],
            dtype=float,
        )
        norm = np.linalg.norm(vector)
        return (vector / norm).tolist()


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
        min_relevance_score=0.3,
        chunk_size=700,
        chunk_overlap=100,
        source_snippet_count=2,
        source_snippet_length=180,
        rag_max_output_tokens=1024,
        image_max_edge=1600,
        log_level="INFO",
    )


def test_reindex_skips_unchanged_documents(tmp_path: Path) -> None:
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    (kb_dir / "python.md").write_text(
        "# Python\n\nUse `py -3.11 -m venv .venv` to create a virtual environment.",
        encoding="utf-8",
    )

    settings = make_settings(tmp_path, kb_dir)
    kb = FakeKnowledgeBase(settings)
    kb.setup()

    first = kb.reindex()
    second = kb.reindex()

    assert first["files_reindexed"] == 1
    assert second["files_reindexed"] == 0


def test_search_reuses_cached_query_embedding(tmp_path: Path) -> None:
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    (kb_dir / "python.md").write_text(
        "# Python\n\nCreate a virtual environment with `py -3.11 -m venv .venv`.",
        encoding="utf-8",
    )

    settings = make_settings(tmp_path, kb_dir)
    kb = FakeKnowledgeBase(settings)
    kb.setup()
    kb.reindex()

    first = kb.search("How do I create a Python virtual environment?")
    second = kb.search("How do I create a Python virtual environment?")

    assert first
    assert second
    assert kb.query_calls == 1
    assert first[0]["document_path"].endswith("python.md")


def test_recent_turns_store_json_payload(tmp_path: Path) -> None:
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    settings = make_settings(tmp_path, kb_dir)
    kb = FakeKnowledgeBase(settings)
    kb.setup()

    kb.add_turn(
        "user-1",
        "ask",
        {
            "mode": "rag",
            "user_message": "How do I create a virtual environment?",
            "rewritten_query": "How do I create a Python virtual environment?",
            "assistant_message": "Use `py -3.11 -m venv .venv`.",
            "sources": [{"document_path": "data/knowledge_base/python.md"}],
        },
    )

    turns = kb.recent_turns("user-1", 3)

    assert len(turns) == 1
    assert turns[0]["user_message"].startswith("How do I create")
    assert turns[0]["rewritten_query"].startswith("How do I create a Python")
    assert turns[0]["assistant_message"].startswith("Use `py -3.11")
