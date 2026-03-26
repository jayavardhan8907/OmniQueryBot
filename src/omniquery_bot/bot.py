from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from omniquery_bot.config import Settings
from omniquery_bot.genai_client import GeminiClient, GenerationError
from omniquery_bot.knowledge_base import KnowledgeBase


LOGGER = logging.getLogger(__name__)


def run() -> None:
    settings = Settings.from_env()
    settings.validate_for_bot()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

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

    gemini = GeminiClient(settings.gemini_api_key or "", settings.genai_model)
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await update.message.reply_text(help_text())

    async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return

        query = " ".join(context.args).strip()
        if not query:
            await update.message.reply_text("Usage: /ask <your question>")
            return

        try:
            message = await asyncio.to_thread(
                answer_query,
                settings,
                kb,
                gemini,
                str(update.effective_user.id),
                query,
            )
            await update.message.reply_text(message)
        except GenerationError:
            LOGGER.exception("Gemini failed during /ask")
            await update.message.reply_text("I hit a generation error while answering that question.")
        except Exception:
            LOGGER.exception("Unexpected failure during /ask")
            await update.message.reply_text("Something went wrong while processing your question.")

    async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return
        await asyncio.to_thread(kb.set_waiting_for_image, str(update.effective_user.id), True)
        await update.message.reply_text(
            "Send me a photo or image file and I will return a short caption plus 3 tags."
        )

    async def image_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return

        attachment = None
        image_name = None
        mime_type = "image/jpeg"

        if update.message.photo:
            attachment = update.message.photo[-1]
        elif update.message.document and update.message.document.mime_type:
            attachment = update.message.document
            image_name = update.message.document.file_name
            mime_type = update.message.document.mime_type

        if attachment is None:
            await update.message.reply_text("Please upload a valid image file.")
            return

        try:
            telegram_file = await attachment.get_file()
            image_bytes = bytes(await telegram_file.download_as_bytearray())
            message = await asyncio.to_thread(
                answer_image,
                settings,
                kb,
                gemini,
                str(update.effective_user.id),
                image_bytes,
                mime_type,
                image_name,
            )
            await update.message.reply_text(message)
        except ValueError as error:
            await update.message.reply_text(str(error))
        except GenerationError:
            LOGGER.exception("Gemini failed during image description")
            await update.message.reply_text("I hit a generation error while describing that image.")
        except Exception:
            LOGGER.exception("Unexpected failure during image upload")
            await update.message.reply_text("Something went wrong while processing the image.")

    async def summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return

        try:
            summary = await asyncio.to_thread(summarize_last, kb, gemini, str(update.effective_user.id))
            if not summary:
                await update.message.reply_text("I do not have a previous answer or image result to summarize yet.")
                return
            await update.message.reply_text(summary)
        except GenerationError:
            LOGGER.exception("Gemini failed during /summarize")
            await update.message.reply_text("I hit a generation error while summarizing the last interaction.")
        except Exception:
            LOGGER.exception("Unexpected failure during /summarize")
            await update.message.reply_text("Something went wrong while generating the summary.")

    async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return
        state = await asyncio.to_thread(kb.user_state, str(update.effective_user.id))
        if state["waiting_for_image"]:
            message = "I am waiting for an image. Upload a photo or image file to continue."
        else:
            message = "Use /ask <query> for text questions or /image to start an image description."
        await update.message.reply_text(message)

    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("summarize", summarize_command))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, image_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text))
    app.run_polling(drop_pending_updates=True)


def help_text() -> str:
    return (
        "OmniQueryBot commands:\n"
        "/help - Show usage instructions.\n"
        "/ask <query> - Ask a question against the local knowledge base.\n"
        "/image - Upload an image for a caption and 3 tags.\n"
        "/summarize - Summarize your last bot interaction."
    )


def answer_query(
    settings: Settings,
    kb: KnowledgeBase,
    gemini: GeminiClient,
    user_id: str,
    query: str,
) -> str:
    sources = kb.search(query)
    if sources:
        history = kb.recent_turns(user_id, settings.history_window)
        answer_text = gemini.answer_with_context(query, sources, history)
    else:
        answer_text = "I couldn't find that in the knowledge base."

    kb.add_turn(
        user_id=user_id,
        kind="ask",
        user_input=query,
        bot_output=answer_text,
        metadata={"sources": sources},
    )
    kb.save_artifact(
        user_id=user_id,
        artifact_type="ask",
        payload={"query": query, "answer": answer_text, "sources": sources},
    )
    return format_rag_message(answer_text, sources, settings)


def answer_image(
    settings: Settings,
    kb: KnowledgeBase,
    gemini: GeminiClient,
    user_id: str,
    image_bytes: bytes,
    mime_type: str,
    image_name: str | None,
) -> str:
    normalized_bytes = normalize_image(image_bytes, settings.image_max_edge)
    result = gemini.describe_image(normalized_bytes, "image/jpeg")
    message = format_image_message(result)
    kb.add_turn(
        user_id=user_id,
        kind="image",
        user_input=image_name or "[image upload]",
        bot_output=message,
        metadata={"mime_type": mime_type, **result},
    )
    kb.save_artifact(
        user_id=user_id,
        artifact_type="image",
        payload={"name": image_name or "uploaded image", **result},
    )
    return message


def summarize_last(kb: KnowledgeBase, gemini: GeminiClient, user_id: str) -> str | None:
    state = kb.user_state(user_id)
    artifact_type = state["last_artifact_type"]
    payload = state["last_artifact_payload"]
    if not artifact_type or not payload:
        return None

    if artifact_type == "ask":
        artifact_text = (
            f"Question: {payload.get('query', '')}\n"
            f"Answer: {payload.get('answer', '')}\n"
            f"Sources: {format_source_names(payload.get('sources', []))}"
        )
    else:
        artifact_text = (
            f"Image name: {payload.get('name', '')}\n"
            f"Caption: {payload.get('caption', '')}\n"
            f"Tags: {', '.join(payload.get('tags', []))}"
        )

    summary = gemini.summarize(artifact_type, artifact_text)
    kb.add_turn(
        user_id=user_id,
        kind="summary",
        user_input=f"summarize {artifact_type}",
        bot_output=summary,
        metadata={"artifact_type": artifact_type},
    )
    return summary


def format_source_names(sources: list[dict]) -> str:
    return ", ".join(
        f"{source.get('document_path', '')} / {source.get('heading', '')}"
        for source in sources
    )


def normalize_image(image_bytes: bytes, max_edge: int) -> bytes:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            rgb_image = image.convert("RGB")
            rgb_image.thumbnail((max_edge, max_edge))
            buffer = BytesIO()
            rgb_image.save(buffer, format="JPEG", quality=90)
            return buffer.getvalue()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("The uploaded file is not a valid image.") from error


def format_rag_message(answer_text: str, sources: list[dict], settings: Settings) -> str:
    lines = [answer_text.strip()]
    if sources:
        lines.append("")
        lines.append("Sources:")
        for source in sources[: settings.source_snippet_count]:
            source_name = Path(source["document_path"]).name
            snippet = " ".join(source["text"].split())
            if len(snippet) > settings.source_snippet_length:
                snippet = f"{snippet[:settings.source_snippet_length].rstrip()}..."
            lines.append(f"- {source_name} / {source['heading']}: {snippet}")

    message = "\n".join(lines).strip()
    if len(message) > 3900:
        message = f"{message[:3897].rstrip()}..."
    return message


def format_image_message(result: dict) -> str:
    return f"Caption: {result['caption']}\nTags: {', '.join(result['tags'])}"
