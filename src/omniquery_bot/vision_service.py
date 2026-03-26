from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import logging
from time import perf_counter

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase
from omniquery_bot.llm_service import ModelGateway


LOGGER = logging.getLogger(__name__)


class ImageDescription(BaseModel):
    caption: str = Field(description="One short sentence describing the image.")
    tags: list[str] = Field(description="Exactly three short lowercase tags.")


@dataclass(slots=True)
class VisionResponse:
    reply: str
    caption: str
    tags: list[str]


class VisionService:
    def __init__(self, settings: Settings, kb: KnowledgeBase, models: ModelGateway) -> None:
        self.settings = settings
        self.kb = kb
        self.models = models

    def describe(self, user_id: str, image_bytes: bytes, mime_type: str, file_name: str) -> VisionResponse:
        started_at = perf_counter()
        LOGGER.info(
            "Vision start | user_id=%s | file_name=%s | mime_type=%s | bytes=%s",
            user_id,
            file_name,
            mime_type,
            len(image_bytes),
        )
        normalize_started_at = perf_counter()
        normalized_bytes = normalize_image(image_bytes, self.settings.image_max_edge)
        LOGGER.info(
            "Vision image normalized | user_id=%s | normalized_bytes=%s | duration_ms=%.1f",
            user_id,
            len(normalized_bytes),
            (perf_counter() - normalize_started_at) * 1000,
        )

        describe_started_at = perf_counter()
        result = self.models.describe_image(
            normalized_bytes,
            "image/jpeg",
            ImageDescription,
            (
                "Return strict JSON with keys caption and tags. "
                "caption must be one short sentence. "
                "tags must be an array of exactly 3 short lowercase strings."
            ),
        )
        LOGGER.info(
            "Vision model output | user_id=%s | duration_ms=%.1f | caption=%s | tags=%s",
            user_id,
            (perf_counter() - describe_started_at) * 1000,
            result.caption,
            result.tags,
        )
        tags = normalize_tags(result.tags)
        caption = result.caption.strip()
        reply = format_image_message(caption, tags)
        self.kb.add_turn(
            user_id,
            "image",
            {
                "mode": "image",
                "user_message": file_name,
                "assistant_message": reply,
                "caption": caption,
                "tags": tags,
            },
        )
        self.kb.set_waiting_for_image(user_id, False)
        LOGGER.info(
            "Vision turn stored | user_id=%s | reply=%s | total_duration_ms=%.1f",
            user_id,
            reply,
            (perf_counter() - started_at) * 1000,
        )
        return VisionResponse(reply=reply, caption=caption, tags=tags)


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


def normalize_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        normalized = str(tag).strip().lower()
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
        if len(cleaned) == 3:
            break
    if len(cleaned) != 3:
        raise ValueError("The model did not return exactly 3 usable tags.")
    return cleaned


def format_image_message(caption: str, tags: list[str]) -> str:
    return f"Caption: {caption}\nTags: {', '.join(tags)}"
