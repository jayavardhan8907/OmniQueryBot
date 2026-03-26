from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import numpy as np

from omniquery_bot.config import Settings


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
    user_input TEXT NOT NULL,
    bot_output TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_state (
    user_id TEXT PRIMARY KEY,
    waiting_for_image INTEGER NOT NULL DEFAULT 0,
    last_artifact_type TEXT,
    last_artifact_payload TEXT NOT NULL DEFAULT '{}',
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

    def reindex(self) -> dict:
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

            chunks = self._split_markdown(text)
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
        embedding = self._cached_query_embedding(normalized_query)
        if embedding is None:
            embedding = self._embed_query(query)
            self._save_query_embedding(normalized_query, embedding)

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT documents.path, documents.title, chunks.heading, chunks.chunk_index, chunks.text, chunks.embedding_json
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
                    "document_path": row["path"],
                    "title": row["title"],
                    "heading": row["heading"],
                    "chunk_index": row["chunk_index"],
                    "text": row["text"],
                    "score": score,
                }
            )

        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[: self.settings.top_k]

    def add_turn(
        self,
        user_id: str,
        kind: str,
        user_input: str,
        bot_output: str,
        metadata: dict | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO turns(user_id, kind, user_input, bot_output, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    kind,
                    user_input,
                    bot_output,
                    json.dumps(metadata or {}),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def recent_turns(self, user_id: str, limit: int) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT user_input, bot_output, kind, metadata_json, created_at
                FROM turns
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

        turns = [
            {
                "user_input": row["user_input"],
                "bot_output": row["bot_output"],
                "kind": row["kind"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        turns.reverse()
        return turns

    def set_waiting_for_image(self, user_id: str, waiting: bool) -> None:
        state = self.user_state(user_id)
        self._save_state(
            user_id=user_id,
            waiting_for_image=waiting,
            last_artifact_type=state["last_artifact_type"],
            last_artifact_payload=state["last_artifact_payload"],
        )

    def save_artifact(self, user_id: str, artifact_type: str, payload: dict) -> None:
        self._save_state(
            user_id=user_id,
            waiting_for_image=False,
            last_artifact_type=artifact_type,
            last_artifact_payload=payload,
        )

    def user_state(self, user_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT waiting_for_image, last_artifact_type, last_artifact_payload
                FROM user_state
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

        if row is None:
            return {
                "waiting_for_image": False,
                "last_artifact_type": None,
                "last_artifact_payload": {},
            }

        return {
            "waiting_for_image": bool(row["waiting_for_image"]),
            "last_artifact_type": row["last_artifact_type"],
            "last_artifact_payload": json.loads(row["last_artifact_payload"]),
        }

    def _save_state(
        self,
        user_id: str,
        waiting_for_image: bool,
        last_artifact_type: str | None,
        last_artifact_payload: dict,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_state(user_id, waiting_for_image, last_artifact_type, last_artifact_payload, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    waiting_for_image = excluded.waiting_for_image,
                    last_artifact_type = excluded.last_artifact_type,
                    last_artifact_payload = excluded.last_artifact_payload,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    int(waiting_for_image),
                    last_artifact_type,
                    json.dumps(last_artifact_payload),
                    datetime.now(UTC).isoformat(),
                ),
            )

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

    def _split_markdown(self, text: str) -> list[dict]:
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

        chunks: list[dict] = []
        for section_heading, body in sections:
            body = re.sub(r"\n{3,}", "\n\n", body).strip()
            if not body:
                continue

            start = 0
            while start < len(body):
                end = min(len(body), start + self.settings.chunk_size)
                if end < len(body):
                    boundary = body.rfind(" ", start, end)
                    if boundary > start + (self.settings.chunk_size // 2):
                        end = boundary
                chunk_text = body[start:end].strip()
                if chunk_text:
                    chunks.append({"heading": section_heading, "text": chunk_text})
                if end >= len(body):
                    break
                next_start = max(0, end - self.settings.chunk_overlap)
                start = end if next_start <= start else next_start
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
            rows = connection.execute("PRAGMA table_info(user_state)").fetchall()
            column_names = {row["name"] for row in rows}
            if "waiting_for_image" in column_names:
                return
            if "awaiting_image" not in column_names:
                return

            connection.execute("ALTER TABLE user_state RENAME TO user_state_legacy")
            connection.execute(
                """
                CREATE TABLE user_state (
                    user_id TEXT PRIMARY KEY,
                    waiting_for_image INTEGER NOT NULL DEFAULT 0,
                    last_artifact_type TEXT,
                    last_artifact_payload TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO user_state(user_id, waiting_for_image, last_artifact_type, last_artifact_payload, updated_at)
                SELECT user_id, awaiting_image, last_artifact_type, last_artifact_payload, updated_at
                FROM user_state_legacy
                """
            )
            connection.execute("DROP TABLE user_state_legacy")
