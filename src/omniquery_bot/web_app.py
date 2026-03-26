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

from omniquery_bot.bot import format_image_message, normalize_image, summarize_last
from omniquery_bot.config import Settings
from omniquery_bot.genai_client import GeminiClient, GenerationError
from omniquery_bot.knowledge_base import KnowledgeBase


LOGGER = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class ChatRequest(BaseModel):
    session_id: str
    message: str


class SessionRequest(BaseModel):
    session_id: str


def create_app(
    settings: Settings | None = None,
    kb: KnowledgeBase | None = None,
    gemini: GeminiClient | None = None,
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

    gemini = gemini or GeminiClient(settings.gemini_api_key or "", settings.genai_model)

    if not WEB_DIR.exists():
        raise FileNotFoundError(f"Missing local web assets directory: {WEB_DIR}")

    app = FastAPI(title="OmniQueryBot Local Web", version="0.1.0")
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
            "model": settings.genai_model,
            "knowledge_base": str(settings.kb_dir),
            "top_k": settings.top_k,
            "history_window": settings.history_window,
        }

    @app.get("/api/history")
    async def history(session_id: str) -> dict:
        normalized_session = _normalize_session_id(session_id)
        turns = await run_in_threadpool(kb.recent_turns, normalized_session, 12)
        messages: list[dict] = []
        for turn in turns:
            messages.append(
                {
                    "role": "user",
                    "kind": turn["kind"],
                    "content": turn["user_input"],
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "kind": turn["kind"],
                    "content": turn["bot_output"],
                }
            )
        return {"messages": messages}

    @app.post("/api/chat")
    async def chat(payload: ChatRequest) -> dict:
        session_id = _normalize_session_id(payload.session_id)
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message is required.")

        try:
            return await run_in_threadpool(_chat_response, settings, kb, gemini, session_id, message)
        except GenerationError as error:
            LOGGER.exception("Generation failed during local chat request")
            raise HTTPException(status_code=502, detail=f"Generation error: {error}") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:  # pragma: no cover - defensive API guard
            LOGGER.exception("Unexpected local chat failure")
            raise HTTPException(status_code=500, detail="Unexpected server error.") from error

    @app.post("/api/image")
    async def image(session_id: str = Form(...), file: UploadFile = File(...)) -> dict:
        normalized_session = _normalize_session_id(session_id)
        try:
            image_bytes = await file.read()
            return await run_in_threadpool(
                _image_response,
                settings,
                kb,
                gemini,
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

    @app.post("/api/summarize")
    async def summarize(payload: SessionRequest) -> dict:
        session_id = _normalize_session_id(payload.session_id)
        try:
            summary = await run_in_threadpool(summarize_last, kb, gemini, session_id)
        except GenerationError as error:
            LOGGER.exception("Generation failed during local summarize request")
            raise HTTPException(status_code=502, detail=f"Generation error: {error}") from error
        except Exception as error:  # pragma: no cover - defensive API guard
            LOGGER.exception("Unexpected local summarize failure")
            raise HTTPException(status_code=500, detail="Unexpected server error.") from error

        if not summary:
            return {"reply": "No previous answer or image result is available yet."}
        return {"reply": summary}

    @app.post("/api/reindex")
    async def reindex() -> dict:
        try:
            stats = await run_in_threadpool(kb.reindex)
        except Exception as error:  # pragma: no cover - defensive API guard
            LOGGER.exception("Unexpected reindex failure")
            raise HTTPException(status_code=500, detail="Unexpected server error.") from error
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


def _chat_response(
    settings: Settings,
    kb: KnowledgeBase,
    gemini: GeminiClient,
    session_id: str,
    message: str,
) -> dict:
    matches = kb.search(message)
    if matches:
        history = kb.recent_turns(session_id, settings.history_window)
        reply = gemini.answer_with_context(message, matches, history)
    else:
        reply = "I couldn't find that in the knowledge base."

    kb.add_turn(
        user_id=session_id,
        kind="ask",
        user_input=message,
        bot_output=reply,
        metadata={"sources": matches},
    )
    kb.save_artifact(
        user_id=session_id,
        artifact_type="ask",
        payload={"query": message, "answer": reply, "sources": matches},
    )
    return {
        "reply": reply,
        "sources": [_serialize_source(match, settings.source_snippet_length) for match in matches],
    }


def _image_response(
    settings: Settings,
    kb: KnowledgeBase,
    gemini: GeminiClient,
    session_id: str,
    image_bytes: bytes,
    mime_type: str,
    file_name: str,
) -> dict:
    if not image_bytes:
        raise ValueError("Upload an image first.")

    normalized_bytes = normalize_image(image_bytes, settings.image_max_edge)
    result = gemini.describe_image(normalized_bytes, "image/jpeg")
    reply = format_image_message(result)

    kb.add_turn(
        user_id=session_id,
        kind="image",
        user_input=file_name,
        bot_output=reply,
        metadata={"mime_type": mime_type, **result},
    )
    kb.save_artifact(
        user_id=session_id,
        artifact_type="image",
        payload={"name": file_name, **result},
    )
    return {
        "reply": reply,
        "caption": result["caption"],
        "tags": result["tags"],
        "file_name": file_name,
    }


def _serialize_source(source: dict, snippet_length: int) -> dict:
    snippet = " ".join(source["text"].split())
    if len(snippet) > snippet_length:
        snippet = f"{snippet[:snippet_length].rstrip()}..."
    return {
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
