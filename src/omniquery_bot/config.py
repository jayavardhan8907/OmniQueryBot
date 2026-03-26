from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (root / path).resolve()


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    telegram_bot_token: str | None
    gemini_api_key: str | None
    genai_model: str
    embedding_model: str
    db_path: Path
    kb_dir: Path
    top_k: int
    history_window: int
    min_relevance_score: float
    chunk_size: int
    chunk_overlap: int
    source_snippet_count: int
    source_snippet_length: int
    image_max_edge: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        project_root = ROOT_DIR
        settings = cls(
            project_root=project_root,
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            genai_model=os.getenv("GENAI_MODEL", "gemini-2.5-flash"),
            embedding_model=os.getenv(
                "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
            ),
            db_path=_resolve_path(os.getenv("DB_PATH", "data/omniquerybot.db"), project_root),
            kb_dir=_resolve_path(os.getenv("KB_DIR", "data/knowledge_base"), project_root),
            top_k=int(os.getenv("TOP_K", "3")),
            history_window=int(os.getenv("HISTORY_WINDOW", "3")),
            min_relevance_score=float(os.getenv("MIN_RELEVANCE_SCORE", "0.32")),
            chunk_size=int(os.getenv("CHUNK_SIZE", "700")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "100")),
            source_snippet_count=int(os.getenv("SOURCE_SNIPPET_COUNT", "2")),
            source_snippet_length=int(os.getenv("SOURCE_SNIPPET_LENGTH", "180")),
            image_max_edge=int(os.getenv("IMAGE_MAX_EDGE", "1600")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
        settings.ensure_directories()
        return settings

    def ensure_directories(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.kb_dir.mkdir(parents=True, exist_ok=True)

    def validate_for_bot(self) -> None:
        missing: list[str] = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required environment variables: {joined}")

    def validate_for_indexing(self) -> None:
        if not self.kb_dir.exists():
            raise ValueError(f"Knowledge base directory does not exist: {self.kb_dir}")

    def validate_for_web(self) -> None:
        if not self.gemini_api_key:
            raise ValueError("Missing required environment variable: GEMINI_API_KEY")
