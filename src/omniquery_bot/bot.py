from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import BotCommand, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase
from omniquery_bot.llm_service import GenerationError, ModelGateway
from omniquery_bot.rag_service import RagService
from omniquery_bot.vision_service import VisionService


LOGGER = logging.getLogger(__name__)
BOT_COMMANDS = [
    BotCommand("help", "Show usage instructions"),
    BotCommand("ask", "Start a knowledge-base question"),
    BotCommand("image", "Upload an image for a caption and 3 tags"),
]


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

    models = ModelGateway(settings)
    rag_service = RagService(settings, kb, models)
    vision_service = VisionService(settings, kb, models)
    async def post_init(application) -> None:
        await application.bot.set_my_commands(BOT_COMMANDS)

    app = ApplicationBuilder().token(settings.telegram_bot_token).post_init(post_init).build()

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await update.message.reply_text(help_text())

    async def answer_query(update: Update, query: str) -> None:
        if update.message is None or update.effective_user is None:
            return

        try:
            result = await asyncio.to_thread(rag_service.answer, str(update.effective_user.id), query)
            await update.message.reply_text(
                format_rag_message(result.reply, result.sources, settings),
            )
        except GenerationError:
            LOGGER.exception("Generation failed during /ask")
            await update.message.reply_text("I hit a generation error while answering that question.")
        except Exception:
            LOGGER.exception("Unexpected failure during /ask")
            await update.message.reply_text("Something went wrong while processing your question.")

    async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return

        query = " ".join(context.args).strip()
        user_id = str(update.effective_user.id)
        await asyncio.to_thread(kb.set_waiting_for_image, user_id, False)
        if not query:
            await asyncio.to_thread(kb.set_waiting_for_ask, user_id, True)
            await update.message.reply_text("Send me your question and I will answer from the local knowledge base.")
            return

        await asyncio.to_thread(kb.set_waiting_for_ask, user_id, False)
        await answer_query(update, query)

    async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return
        user_id = str(update.effective_user.id)
        await asyncio.to_thread(kb.set_waiting_for_ask, user_id, False)
        await asyncio.to_thread(kb.set_waiting_for_image, user_id, True)
        await update.message.reply_text(
            "Send me a photo or image file and I will return a short caption plus 3 tags."
        )

    async def image_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return

        attachment = None
        image_name = "uploaded-image"
        mime_type = "image/jpeg"

        if update.message.photo:
            attachment = update.message.photo[-1]
        elif update.message.document and update.message.document.mime_type:
            attachment = update.message.document
            image_name = update.message.document.file_name or image_name
            mime_type = update.message.document.mime_type

        if attachment is None:
            await update.message.reply_text("Please upload a valid image file.")
            return

        try:
            telegram_file = await attachment.get_file()
            image_bytes = bytes(await telegram_file.download_as_bytearray())
            result = await asyncio.to_thread(
                vision_service.describe,
                str(update.effective_user.id),
                image_bytes,
                mime_type,
                image_name,
            )
            await update.message.reply_text(result.reply)
        except ValueError as error:
            await asyncio.to_thread(kb.set_waiting_for_image, str(update.effective_user.id), False)
            await update.message.reply_text(str(error))
        except GenerationError:
            await asyncio.to_thread(kb.set_waiting_for_image, str(update.effective_user.id), False)
            LOGGER.exception("Generation failed during image upload")
            await update.message.reply_text(
                "I hit a generation error while describing that image. Send /image and try again."
            )
        except Exception:
            await asyncio.to_thread(kb.set_waiting_for_image, str(update.effective_user.id), False)
            LOGGER.exception("Unexpected failure during image upload")
            await update.message.reply_text("Something went wrong while processing the image.")

    async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return
        user_id = str(update.effective_user.id)
        waiting_for_image = await asyncio.to_thread(kb.is_waiting_for_image, user_id)
        if waiting_for_image:
            message = "I am waiting for an image. Upload a photo or image file to continue."
            await update.message.reply_text(message)
            return

        waiting_for_ask = await asyncio.to_thread(kb.is_waiting_for_ask, user_id)
        if waiting_for_ask:
            await asyncio.to_thread(kb.set_waiting_for_ask, user_id, False)
            query = (update.message.text or "").strip()
            if not query:
                await update.message.reply_text("Send me your question after /ask.")
                return
            await answer_query(update, query)
            return

        if update.message.text and update.message.text.strip():
            message = "Use /ask to start a question, or /image to upload an image."
        else:
            message = "Use /ask to start a question, or /image to upload an image."
        await update.message.reply_text(message)

    async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await update.message.reply_text(
            "Unknown command. Use /help, /ask, or /image."
        )

    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, image_upload))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text))
    app.run_polling(drop_pending_updates=True)


def help_text() -> str:
    return (
        "OmniQueryBot commands:\n"
        "/help - Show usage instructions.\n"
        "/ask - Start a knowledge-base question. You can also use /ask <query> directly.\n"
        "/image - Upload an image and get 1 caption plus 3 tags.\n\n"
        "Scope:\n"
        "- /ask answers only from the local knowledge base.\n"
        "- /image returns the assignment-required caption and 3 tags."
    )


def format_rag_message(answer_text: str, sources: list[dict], settings: Settings) -> str:
    lines = [answer_text.strip()]
    if sources:
        lines.append("")
        lines.append("Sources:")
        for source in sources[: settings.source_snippet_count]:
            document_path = str(source["document_path"]).replace("\\", "/")
            lines.append(f"- {document_path} | {source['heading']}")

    message = "\n".join(lines).strip()
    if len(message) > 3900:
        message = f"{message[:3897].rstrip()}..."
    return message
