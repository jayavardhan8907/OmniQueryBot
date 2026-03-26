from __future__ import annotations

import ast
import base64
import json
import logging
import re
from typing import Any

from google import genai
from google.genai import types
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from omniquery_bot.config import Settings


LOGGER = logging.getLogger(__name__)
OLLAMA_DEFAULT_MAX_OUTPUT_TOKENS = 64
GEMINI_DEFAULT_MAX_OUTPUT_TOKENS = 256
STRUCTURED_DEFAULT_MAX_OUTPUT_TOKENS = 256


class GenerationError(RuntimeError):
    pass


class _GeminiMessage:
    def __init__(self, content: str, response_metadata: dict[str, Any] | None = None) -> None:
        self.content = content
        self.response_metadata = response_metadata or {}
        self.additional_kwargs: dict[str, Any] = {}


class _GeminiTextModel:
    def __init__(
        self,
        gateway: "ModelGateway",
        model_name: str,
        temperature: float,
        max_output_tokens: int | None,
    ) -> None:
        self.gateway = gateway
        self.model_name = model_name
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    def invoke(self, messages: list[Any], **_: Any) -> _GeminiMessage:
        system_instruction, prompt = _gemini_prompt(messages)
        try:
            response = self.gateway._gemini().models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    systemInstruction=system_instruction,
                    temperature=self.temperature,
                    maxOutputTokens=self.max_output_tokens,
                ),
            )
        except Exception as error:
            raise GenerationError(f"Gemini text generation failed: {error}") from error
        return _GeminiMessage(
            content=coerce_text(response.text),
            response_metadata=_gemini_response_metadata(response, self.model_name),
        )


class _GeminiStructuredTextModel:
    def __init__(
        self,
        gateway: "ModelGateway",
        model_name: str,
        schema: type[BaseModel],
        temperature: float,
        max_output_tokens: int | None,
    ) -> None:
        self.gateway = gateway
        self.model_name = model_name
        self.schema = schema
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    def invoke(self, messages: list[Any], **_: Any) -> BaseModel:
        system_instruction, prompt = _gemini_prompt(messages)
        schema_name = getattr(self.schema, "__name__", "ResponseSchema")
        try:
            response = self.gateway._gemini().models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    systemInstruction=(
                        f"{system_instruction}\n\n"
                        f"Return strict JSON that validates against the {schema_name} schema."
                    ).strip(),
                    temperature=self.temperature,
                    maxOutputTokens=self.max_output_tokens,
                    responseMimeType="application/json",
                ),
            )
        except Exception as error:
            raise GenerationError(f"Gemini structured generation failed: {error}") from error
        payload = _parse_json(coerce_text(response.text))
        try:
            return self.schema.model_validate(payload)
        except Exception as error:
            raise GenerationError("Gemini returned an invalid structured payload.") from error


class ModelGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._gemini_client: genai.Client | None = None

    def chat_model(
        self,
        temperature: float = 0.2,
        *,
        reasoning: bool | str | None = "low",
        num_predict: int | None = None,
    ):
        if self.settings.text_provider == "gemini":
            max_output_tokens = num_predict or GEMINI_DEFAULT_MAX_OUTPUT_TOKENS
            LOGGER.info(
                "ModelGateway text model | provider=gemini | model=%s | temperature=%s | max_output_tokens=%s",
                self.settings.text_model,
                temperature,
                max_output_tokens,
            )
            return _GeminiTextModel(
                gateway=self,
                model_name=self.settings.text_model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        max_output_tokens = num_predict or OLLAMA_DEFAULT_MAX_OUTPUT_TOKENS
        LOGGER.info(
            "ModelGateway text model | provider=ollama | model=%s | base_url=%s | temperature=%s | reasoning=%s | num_predict=%s",
            self.settings.text_model,
            self.settings.ollama_base_url,
            temperature,
            reasoning,
            max_output_tokens,
        )
        return ChatOllama(
            model=self.settings.text_model,
            base_url=self.settings.ollama_base_url,
            temperature=temperature,
            reasoning=reasoning,
            num_predict=max_output_tokens,
        )

    def structured_chat_model(self, schema: type[BaseModel], temperature: float = 0.0):
        if self.settings.text_provider == "gemini":
            LOGGER.info(
                "ModelGateway structured text model | provider=gemini | model=%s | temperature=%s | max_output_tokens=%s",
                self.settings.text_model,
                temperature,
                STRUCTURED_DEFAULT_MAX_OUTPUT_TOKENS,
            )
            return _GeminiStructuredTextModel(
                gateway=self,
                model_name=self.settings.text_model,
                schema=schema,
                temperature=temperature,
                max_output_tokens=STRUCTURED_DEFAULT_MAX_OUTPUT_TOKENS,
            )
        return self.chat_model(
            temperature=temperature,
            reasoning=False,
            num_predict=STRUCTURED_DEFAULT_MAX_OUTPUT_TOKENS,
        ).with_structured_output(schema)

    def describe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        schema: type[BaseModel],
        instruction: str,
    ) -> BaseModel:
        if self.settings.vision_provider == "gemini":
            LOGGER.info("ModelGateway vision model | provider=gemini | model=%s", self.settings.gemini_model)
            return self._describe_image_with_gemini(image_bytes, mime_type, schema, instruction)
        try:
            LOGGER.info(
                "ModelGateway vision model | provider=ollama | model=%s | base_url=%s | mime_type=%s",
                self.settings.vision_model,
                self.settings.ollama_base_url,
                mime_type,
            )
            return self._describe_image_with_ollama(image_bytes, mime_type, schema, instruction)
        except Exception as error:
            LOGGER.exception("ModelGateway Ollama vision call failed")
            if self.settings.gemini_api_key:
                LOGGER.info("ModelGateway vision fallback | provider=gemini | model=%s", self.settings.gemini_model)
                return self._describe_image_with_gemini(image_bytes, mime_type, schema)
            raise GenerationError(f"Ollama image generation failed: {error}") from error

    def _describe_image_with_ollama(
        self,
        image_bytes: bytes,
        mime_type: str,
        schema: type[BaseModel],
        instruction: str,
    ) -> BaseModel:
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        message = HumanMessage(
            content=[
                {"type": "image_url", "image_url": f"data:{mime_type};base64,{encoded}"},
                {"type": "text", "text": instruction},
            ]
        )
        model = ChatOllama(
            model=self.settings.vision_model,
            base_url=self.settings.ollama_base_url,
            temperature=0.2,
            reasoning=False,
        ).with_structured_output(schema)
        return model.invoke([message])

    def _describe_image_with_gemini(
        self,
        image_bytes: bytes,
        mime_type: str,
        schema: type[BaseModel],
        instruction: str,
    ) -> BaseModel:
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        message = HumanMessage(
            content=[
                {"type": "text", "text": instruction},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                },
            ]
        )
        model = ChatGoogleGenerativeAI(
            model=self.settings.gemini_model,
            api_key=self.settings.gemini_api_key,
            temperature=0.2,
            max_tokens=180,
            disable_streaming=True,
        ).with_structured_output(
            schema,
            method="json_schema",
            include_raw=True,
        )
        try:
            response = model.invoke([message])
        except Exception as error:
            raise GenerationError(f"Gemini image generation failed: {error}") from error

        parsed, raw_text, parsing_error = _structured_result_parts(response)
        if raw_text:
            LOGGER.info(
                "ModelGateway Gemini vision raw output | model=%s | preview=%s",
                self.settings.gemini_model,
                _preview_text(raw_text, 220),
            )
        if parsing_error is not None:
            LOGGER.warning(
                "ModelGateway Gemini vision structured parse fallback | model=%s | error=%s",
                self.settings.gemini_model,
                parsing_error,
            )
        if parsed is not None:
            payload = parsed.model_dump() if isinstance(parsed, BaseModel) else parsed
            try:
                return schema.model_validate(payload)
            except Exception as error:
                LOGGER.warning(
                    "ModelGateway Gemini vision parsed payload validation fallback | model=%s | error=%s",
                    self.settings.gemini_model,
                    error,
                )
        if not raw_text:
            raise GenerationError("Gemini returned no usable image payload.")
        payload = _parse_image_payload(raw_text)
        try:
            return schema.model_validate(payload)
        except Exception as error:
            raise GenerationError("Gemini returned an invalid image payload.") from error

    def _gemini(self) -> genai.Client:
        if not self.settings.gemini_api_key:
            raise GenerationError("Gemini fallback is not configured.")
        if self._gemini_client is None:
            self._gemini_client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._gemini_client


def _parse_json(raw_text: str) -> dict[str, Any]:
    if not raw_text:
        raise GenerationError("The model returned an empty JSON payload.")

    normalized = raw_text.strip()
    candidates = [normalized]
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", normalized, flags=re.IGNORECASE | re.DOTALL).strip()
    if fenced and fenced not in candidates:
        candidates.append(fenced)
    if "{" in raw_text and "}" in raw_text:
        candidates.append(raw_text[raw_text.find("{") : raw_text.rfind("}") + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(candidate)
            except (ValueError, SyntaxError):
                continue
        if isinstance(parsed, dict):
            return parsed

    raise GenerationError("The model returned malformed JSON.")


def _parse_image_payload(raw_text: str) -> dict[str, Any]:
    try:
        return _parse_json(raw_text)
    except GenerationError:
        pass

    caption_match = re.search(
        r'(?is)(?:^|\n)\s*(?:caption|"caption")\s*[:=-]\s*["`]?(.+?)["`]?\s*(?:\n|$)',
        raw_text,
    )
    tags_match = re.search(
        r'(?is)(?:^|\n)\s*(?:tags|"tags")\s*[:=-]\s*(.+?)(?:\n|$)',
        raw_text,
    )
    if caption_match and tags_match:
        tags = _split_tags(tags_match.group(1))
        if tags:
            return {
                "caption": caption_match.group(1).strip(" `\"'"),
                "tags": tags,
            }

    lines = [line.strip("- *\t ") for line in raw_text.splitlines() if line.strip()]
    if len(lines) >= 2:
        first = lines[0]
        second = lines[1]
        if first.lower().startswith("caption"):
            tags = _split_tags(second)
            if tags:
                return {
                    "caption": first.split(":", 1)[-1].strip(" `\"'"),
                    "tags": tags,
                }

    raise GenerationError("The model returned malformed JSON.")


def _split_tags(raw_tags: str) -> list[str]:
    cleaned = raw_tags.strip().strip("[]")
    if not cleaned:
        return []
    parts = re.split(r"[,|/]\s*|\s{2,}", cleaned)
    tags = [part.strip(" `\"'") for part in parts if part.strip(" `\"'")]
    return tags


def coerce_text(content: Any) -> str:
    if isinstance(content, str):
        return _strip_think_tags(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(text)
            elif item:
                parts.append(str(item).strip())
        return _strip_think_tags("\n".join(part for part in parts if part))
    return _strip_think_tags(str(content or ""))


def _strip_think_tags(value: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", value, flags=re.IGNORECASE | re.DOTALL)
    if "</think>" in cleaned.lower():
        cleaned = re.split(r"</think>", cleaned, flags=re.IGNORECASE)[-1]
    cleaned = re.sub(r"(?is)^.*?<think>", "", cleaned)
    return cleaned.strip()


def _gemini_prompt(messages: list[Any]) -> tuple[str, str]:
    system_parts: list[str] = []
    content_parts: list[str] = []
    for message in messages:
        text = coerce_text(getattr(message, "content", ""))
        if not text:
            continue
        message_type = str(getattr(message, "type", "human")).lower()
        if message_type == "system":
            system_parts.append(text)
            continue
        role = {
            "human": "User",
            "ai": "Assistant",
        }.get(message_type, message_type.title() or "User")
        content_parts.append(f"{role}:\n{text}")
    prompt = "\n\n".join(content_parts).strip()
    return ("\n\n".join(system_parts).strip(), prompt)


def _gemini_response_metadata(response: Any, model_name: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"model_name": model_name}
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        usage_payload = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
        if "prompt_token_count" in usage_payload:
            metadata["prompt_token_count"] = usage_payload["prompt_token_count"]
        if "candidates_token_count" in usage_payload:
            metadata["candidates_token_count"] = usage_payload["candidates_token_count"]
        if "total_token_count" in usage_payload:
            metadata["total_token_count"] = usage_payload["total_token_count"]
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        first = candidates[0]
        finish_reason = getattr(first, "finish_reason", None)
        if finish_reason is not None:
            metadata["done_reason"] = str(finish_reason)
    return metadata


def _preview_text(value: str, limit: int) -> str:
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _structured_result_parts(result: Any) -> tuple[Any | None, str, Any | None]:
    if isinstance(result, dict):
        raw = result.get("raw")
        parsed = result.get("parsed")
        parsing_error = result.get("parsing_error")
    else:
        raw = None
        parsed = result
        parsing_error = None
    raw_text = coerce_text(getattr(raw, "content", ""))
    return parsed, raw_text, parsing_error
