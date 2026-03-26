from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter

from omniquery_bot.config import Settings


LOGGER = logging.getLogger(__name__)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    heading TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS query_cache (
    query_hash TEXT PRIMARY KEY,
    normalized_query TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    turn_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_user_created_at
ON turns(user_id, created_at);

CREATE TABLE IF NOT EXISTS user_state (
    user_id TEXT PRIMARY KEY,
    waiting_for_image INTEGER NOT NULL DEFAULT 0,
    waiting_for_ask INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""


class KnowledgeBase:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_path = settings.db_path
        self.kb_dir = settings.kb_dir
        self._embedder = None

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def setup(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
        self._migrate_schema_if_needed()

    def reindex(self) -> dict[str, int]:
        stats = {"files_seen": 0, "files_reindexed": 0, "files_removed": 0, "chunks_written": 0}
        known_paths: set[str] = set()
        existing_hashes = self._document_hashes()

        for path in self._kb_files():
            stats["files_seen"] += 1
            relative_path = path.relative_to(self.settings.project_root).as_posix()
            known_paths.add(relative_path)

            text = path.read_text(encoding="utf-8")
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if existing_hashes.get(relative_path) == content_hash:
                continue

            chunks = self._split_document(text)
            embeddings = self._embed_texts([chunk["text"] for chunk in chunks])

            with self.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO documents(path, title, content_hash, indexed_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        title = excluded.title,
                        content_hash = excluded.content_hash,
                        indexed_at = excluded.indexed_at
                    """,
                    (
                        relative_path,
                        self._title_for(path, text),
                        content_hash,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                document_id = connection.execute(
                    "SELECT id FROM documents WHERE path = ?",
                    (relative_path,),
                ).fetchone()["id"]
                connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
                connection.executemany(
                    """
                    INSERT INTO chunks(document_id, chunk_index, heading, text, embedding_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            document_id,
                            index,
                            chunk["heading"],
                            chunk["text"],
                            json.dumps(embedding),
                        )
                        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True))
                    ],
                )

            stats["files_reindexed"] += 1
            stats["chunks_written"] += len(chunks)

        stats["files_removed"] = self._delete_missing_documents(known_paths)
        return stats

    def search(self, query: str) -> list[dict]:
        normalized_query = re.sub(r"\s+", " ", query.strip().lower())
        LOGGER.info("KB search start | query=%s | normalized_query=%s", query, normalized_query)
        embedding = self._cached_query_embedding(normalized_query)
        if embedding is None:
            LOGGER.info("KB query embedding cache miss | query=%s", normalized_query)
            embedding = self._embed_query(normalized_query)
            self._save_query_embedding(normalized_query, embedding)
        else:
            LOGGER.info("KB query embedding cache hit | query=%s", normalized_query)

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    chunks.id AS chunk_id,
                    documents.path,
                    documents.title,
                    chunks.heading,
                    chunks.chunk_index,
                    chunks.text,
                    chunks.embedding_json
                FROM chunks
                INNER JOIN documents ON documents.id = chunks.document_id
                ORDER BY documents.path, chunks.chunk_index
                """
            ).fetchall()

        query_vector = np.array(embedding, dtype=float)
        matches: list[dict] = []
        for row in rows:
            chunk_vector = np.array(json.loads(row["embedding_json"]), dtype=float)
            score = float(np.dot(query_vector, chunk_vector))
            if score < self.settings.min_relevance_score:
                continue
            matches.append(
                {
                    "chunk_id": row["chunk_id"],
                    "document_path": row["path"],
                    "title": row["title"],
                    "heading": row["heading"],
                    "chunk_index": row["chunk_index"],
                    "text": row["text"],
                    "score": score,
                }
                )

        matches.sort(key=lambda item: item["score"], reverse=True)
        top_matches = matches[: self.settings.top_k]
        LOGGER.info(
            "KB search complete | query=%s | scanned_chunks=%s | matched_chunks=%s | returned=%s",
            normalized_query,
            len(rows),
            len(matches),
            len(top_matches),
        )
        return top_matches

    def add_turn(self, user_id: str, kind: str, payload: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO turns(user_id, kind, turn_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    kind,
                    json.dumps(payload),
                    datetime.now(UTC).isoformat(),
                ),
            )
        LOGGER.info("KB turn stored | user_id=%s | kind=%s", user_id, kind)

    def recent_turns(self, user_id: str, limit: int) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT kind, turn_json, created_at
                FROM turns
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

        turns = [
            {
                "kind": row["kind"],
                **json.loads(row["turn_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        turns.reverse()
        LOGGER.info("KB recent turns loaded | user_id=%s | requested=%s | returned=%s", user_id, limit, len(turns))
        return turns

    def set_waiting_for_image(self, user_id: str, waiting: bool) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_state(user_id, waiting_for_image, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    waiting_for_image = excluded.waiting_for_image,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    int(waiting),
                    datetime.now(UTC).isoformat(),
                ),
            )
        LOGGER.info("KB user state updated | user_id=%s | waiting_for_image=%s", user_id, waiting)

    def is_waiting_for_image(self, user_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT waiting_for_image FROM user_state WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return bool(row["waiting_for_image"]) if row is not None else False

    def set_waiting_for_ask(self, user_id: str, waiting: bool) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_state(user_id, waiting_for_ask, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    waiting_for_ask = excluded.waiting_for_ask,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    int(waiting),
                    datetime.now(UTC).isoformat(),
                ),
            )
        LOGGER.info("KB user state updated | user_id=%s | waiting_for_ask=%s", user_id, waiting)

    def is_waiting_for_ask(self, user_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT waiting_for_ask FROM user_state WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return bool(row["waiting_for_ask"]) if row is not None else False

    def _document_hashes(self) -> dict[str, str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT path, content_hash FROM documents").fetchall()
        return {row["path"]: row["content_hash"] for row in rows}

    def _delete_missing_documents(self, valid_paths: set[str]) -> int:
        with self.connect() as connection:
            rows = connection.execute("SELECT path FROM documents").fetchall()
            stale_paths = [row["path"] for row in rows if row["path"] not in valid_paths]
            if stale_paths:
                connection.executemany(
                    "DELETE FROM documents WHERE path = ?",
                    [(path,) for path in stale_paths],
                )
            return len(stale_paths)

    def _cached_query_embedding(self, normalized_query: str) -> list[float] | None:
        query_hash = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT embedding_json FROM query_cache WHERE query_hash = ?",
                (query_hash,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["embedding_json"])

    def _save_query_embedding(self, normalized_query: str, embedding: list[float]) -> None:
        query_hash = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO query_cache(query_hash, normalized_query, embedding_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(query_hash) DO UPDATE SET
                    normalized_query = excluded.normalized_query,
                    embedding_json = excluded.embedding_json,
                    created_at = excluded.created_at
                """,
                (
                    query_hash,
                    normalized_query,
                    json.dumps(embedding),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def _kb_files(self) -> list[Path]:
        files = [path for path in self.kb_dir.rglob("*") if path.suffix.lower() in {".md", ".txt"}]
        return sorted(path for path in files if path.is_file())

    def _title_for(self, path: Path, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return path.stem.replace("_", " ").replace("-", " ").title()

    def _split_document(self, text: str) -> list[dict]:
        sections: list[tuple[str, str]] = []
        heading = "Overview"
        lines: list[str] = []

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if stripped.startswith("#"):
                section_text = "\n".join(lines).strip()
                if section_text:
                    sections.append((heading, section_text))
                heading = stripped.lstrip("#").strip() or "Overview"
                lines = []
                continue
            lines.append(line)

        trailing = "\n".join(lines).strip()
        if trailing:
            sections.append((heading, trailing))
        if not sections and text.strip():
            sections.append(("Overview", text.strip()))

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        chunks: list[dict] = []
        for section_heading, body in sections:
            body = re.sub(r"\n{3,}", "\n\n", body).strip()
            if not body:
                continue
            for chunk_text in splitter.split_text(body):
                cleaned = chunk_text.strip()
                if cleaned:
                    chunks.append({"heading": section_heading, "text": cleaned})
        return chunks

    def _embedder_model(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(self.settings.embedding_model)
        return self._embedder

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings = self._embedder_model().encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return [embedding.astype(float).tolist() for embedding in embeddings]

    def _embed_query(self, query: str) -> list[float]:
        embedding = self._embedder_model().encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0]
        return embedding.astype(float).tolist()

    def _migrate_schema_if_needed(self) -> None:
        with self.connect() as connection:
            turn_columns = {row["name"] for row in connection.execute("PRAGMA table_info(turns)").fetchall()}
            if turn_columns and "turn_json" not in turn_columns:
                rows = connection.execute(
                    """
                    SELECT user_id, kind, user_input, bot_output, metadata_json, created_at
                    FROM turns
                    """
                ).fetchall()
                connection.execute("ALTER TABLE turns RENAME TO turns_legacy")
                connection.execute(
                    """
                    CREATE TABLE turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        turn_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                for row in rows:
                    payload = {
                        "user_message": row["user_input"],
                        "assistant_message": row["bot_output"],
                    }
                    metadata = json.loads(row["metadata_json"] or "{}")
                    if metadata:
                        payload["metadata"] = metadata
                    connection.execute(
                        """
                        INSERT INTO turns(user_id, kind, turn_json, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            row["user_id"],
                            row["kind"],
                            json.dumps(payload),
                            row["created_at"],
                        ),
                    )
                connection.execute("DROP TABLE turns_legacy")
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_turns_user_created_at
                    ON turns(user_id, created_at)
                    """
                )

            user_state_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(user_state)").fetchall()
            }
            if user_state_columns and (
                "last_artifact_type" in user_state_columns or "awaiting_image" in user_state_columns
            ):
                waiting_column = "waiting_for_image" if "waiting_for_image" in user_state_columns else "awaiting_image"
                rows = connection.execute(
                    f"SELECT user_id, {waiting_column} AS waiting_for_image, updated_at FROM user_state"
                ).fetchall()
                connection.execute("ALTER TABLE user_state RENAME TO user_state_legacy")
                connection.execute(
                    """
                    CREATE TABLE user_state (
                        user_id TEXT PRIMARY KEY,
                        waiting_for_image INTEGER NOT NULL DEFAULT 0,
                        waiting_for_ask INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                for row in rows:
                    connection.execute(
                        """
                        INSERT INTO user_state(user_id, waiting_for_image, updated_at)
                        VALUES (?, ?, ?)
                        """,
                        (row["user_id"], row["waiting_for_image"], row["updated_at"]),
                    )
                connection.execute("DROP TABLE user_state_legacy")
            elif user_state_columns and "waiting_for_ask" not in user_state_columns:
                connection.execute(
                    """
                    ALTER TABLE user_state
                    ADD COLUMN waiting_for_ask INTEGER NOT NULL DEFAULT 0
                    """
                )
