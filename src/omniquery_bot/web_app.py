from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase
from omniquery_bot.llm_service import GenerationError, ModelGateway
from omniquery_bot.rag_service import RagService
from omniquery_bot.vision_service import VisionService


LOGGER = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class ChatRequest(BaseModel):
    session_id: str
    message: str


def create_app(
    settings: Settings | None = None,
    kb: KnowledgeBase | None = None,
    rag_service: RagService | None = None,
    vision_service: VisionService | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate_for_web()

    if kb is None:
        kb = KnowledgeBase(settings)
        kb.setup()
        stats = kb.reindex()
        LOGGER.info(
            "Knowledge base sync complete: files_seen=%s files_reindexed=%s files_removed=%s chunks_written=%s",
            stats["files_seen"],
            stats["files_reindexed"],
            stats["files_removed"],
            stats["chunks_written"],
        )

    models = ModelGateway(settings)
    rag_service = rag_service or RagService(settings, kb, models)
    vision_service = vision_service or VisionService(settings, kb, models)

    if not WEB_DIR.exists():
        raise FileNotFoundError(f"Missing local web assets directory: {WEB_DIR}")

    app = FastAPI(title="OmniQueryBot Local Chat", version="0.2.0")
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/config")
    async def config() -> dict:
        return {
            "text_model": settings.text_model,
            "vision_model": settings.vision_model,
            "embedding_model": settings.embedding_model,
            "knowledge_base": str(settings.kb_dir),
            "top_k": settings.top_k,
            "history_window": settings.history_window,
        }

    @app.get("/api/history")
    async def history(session_id: str) -> dict:
        normalized_session = _normalize_session_id(session_id)
        LOGGER.info("API history request | session_id=%s", normalized_session)
        turns = await run_in_threadpool(kb.recent_turns, normalized_session, 12)
        messages: list[dict] = []
        for turn in turns:
            messages.append(
                {
                    "role": "user",
                    "kind": turn["kind"],
                    "content": turn.get("user_message", ""),
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "kind": turn["kind"],
                    "content": turn.get("assistant_message", ""),
                    "tags": turn.get("tags", []),
                }
            )
        return {"messages": messages}

    @app.post("/api/chat")
    async def chat(payload: ChatRequest) -> dict:
        session_id = _normalize_session_id(payload.session_id)
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message is required.")
        LOGGER.info("API chat request | session_id=%s | message=%s", session_id, message)

        try:
            result = await run_in_threadpool(rag_service.answer, session_id, message)
        except GenerationError as error:
            LOGGER.exception("Generation failed during local chat request")
            raise HTTPException(status_code=502, detail=f"Generation error: {error}") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:  # pragma: no cover - defensive API guard
            LOGGER.exception("Unexpected local chat failure")
            raise HTTPException(status_code=500, detail="Unexpected server error.") from error

        LOGGER.info(
            "API chat response | session_id=%s | route=%s | rewritten_query=%s | source_count=%s | reply=%s",
            session_id,
            result.route,
            result.rewritten_query,
            len(result.sources),
            result.reply,
        )
        return {
            "reply": result.reply,
            "route": result.route,
            "rewritten_query": result.rewritten_query,
            "sources": [_serialize_source(source, settings.source_snippet_length) for source in result.sources],
        }

    @app.post("/api/image")
    async def image(session_id: str = Form(...), file: UploadFile = File(...)) -> dict:
        normalized_session = _normalize_session_id(session_id)
        LOGGER.info(
            "API image request | session_id=%s | file_name=%s | mime_type=%s",
            normalized_session,
            file.filename or "uploaded-image",
            file.content_type or "application/octet-stream",
        )
        try:
            image_bytes = await file.read()
            result = await run_in_threadpool(
                vision_service.describe,
                normalized_session,
                image_bytes,
                file.content_type or "application/octet-stream",
                file.filename or "uploaded-image",
            )
        except GenerationError as error:
            LOGGER.exception("Generation failed during local image request")
            raise HTTPException(status_code=502, detail=f"Generation error: {error}") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:  # pragma: no cover - defensive API guard
            LOGGER.exception("Unexpected local image failure")
            raise HTTPException(status_code=500, detail="Unexpected server error.") from error

        LOGGER.info(
            "API image response | session_id=%s | caption=%s | tags=%s",
            normalized_session,
            result.caption,
            result.tags,
        )
        return {
            "reply": result.reply,
            "caption": result.caption,
            "tags": result.tags,
            "file_name": file.filename or "uploaded-image",
        }

    @app.post("/api/reindex")
    async def reindex() -> dict:
        LOGGER.info("API reindex request")
        try:
            stats = await run_in_threadpool(kb.reindex)
        except Exception as error:  # pragma: no cover - defensive API guard
            LOGGER.exception("Unexpected reindex failure")
            raise HTTPException(status_code=500, detail="Unexpected server error.") from error
        LOGGER.info("API reindex response | stats=%s", stats)
        return {"stats": stats}

    return app


def run() -> None:
    settings = Settings.from_env()
    settings.validate_for_web()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    uvicorn.run(create_app(settings=settings), host=host, port=port, log_level=settings.log_level.lower())


def _serialize_source(source: dict, snippet_length: int) -> dict:
    snippet = " ".join(source["text"].split())
    if len(snippet) > snippet_length:
        snippet = f"{snippet[:snippet_length].rstrip()}..."
    return {
        "chunk_id": source["chunk_id"],
        "file_name": Path(source["document_path"]).name,
        "document_path": source["document_path"],
        "heading": source["heading"],
        "score": round(float(source["score"]), 3),
        "snippet": snippet,
    }


def _normalize_session_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Session id is required.")
    return normalized
