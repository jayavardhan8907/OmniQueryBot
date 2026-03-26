from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from dataclasses import dataclass
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from omniquery_bot.config import Settings
from omniquery_bot.knowledge_base import KnowledgeBase
from omniquery_bot.llm_service import GenerationError, ModelGateway, coerce_text


LOGGER = logging.getLogger(__name__)


class RewriteDecision(BaseModel):
    route: Literal["greeting", "rag"] = Field(description="Whether to answer directly or use retrieval.")
    standalone_query: str = Field(default="", description="Standalone version of the latest user request.")
    reply: str = Field(default="", description="Short direct reply used only for greetings or small talk.")


@dataclass(slots=True)
class RagResponse:
    reply: str
    sources: list[dict]
    route: str
    rewritten_query: str


class RagService:
    def __init__(self, settings: Settings, kb: KnowledgeBase, models: ModelGateway) -> None:
        self.settings = settings
        self.kb = kb
        self.models = models

    def answer(self, user_id: str, question: str) -> RagResponse:
        started_at = perf_counter()
        LOGGER.info("RAG start | user_id=%s | question=%s", user_id, question)

        history_started_at = perf_counter()
        history = self.kb.recent_turns(user_id, self.settings.history_window)
        LOGGER.info(
            "RAG memory loaded | user_id=%s | turns=%s | duration_ms=%.1f | memory=%s",
            user_id,
            len(history),
            (perf_counter() - history_started_at) * 1000,
            _to_json(memory_payload(history)),
        )

        if is_simple_greeting(question):
            reply = "Hello! Ask me about the stored docs with /ask, or use /image for image captions."
            payload = {
                "mode": "greeting",
                "user_message": question,
                "rewritten_query": "",
                "assistant_message": reply,
                "sources": [],
            }
            self.kb.add_turn(user_id, "ask", payload)
            LOGGER.info(
                "RAG greeting fast-path | user_id=%s | reply=%s | total_duration_ms=%.1f",
                user_id,
                reply,
                (perf_counter() - started_at) * 1000,
            )
            return RagResponse(reply=reply, sources=[], route="greeting", rewritten_query="")

        if not history:
            decision = RewriteDecision(route="rag", standalone_query=question.strip(), reply="")
            LOGGER.info(
                "RAG rewrite skipped | user_id=%s | reason=no_history | decision=%s",
                user_id,
                _to_json(decision.model_dump()),
            )
        else:
            rewrite_started_at = perf_counter()
            try:
                decision = self._rewrite_or_route(question, history)
                LOGGER.info(
                    "RAG rewrite complete | user_id=%s | duration_ms=%.1f | decision=%s",
                    user_id,
                    (perf_counter() - rewrite_started_at) * 1000,
                    _to_json(decision.model_dump()),
                )
            except GenerationError as error:
                decision = RewriteDecision(route="rag", standalone_query=question.strip(), reply="")
                LOGGER.warning(
                    "RAG rewrite fallback | user_id=%s | duration_ms=%.1f | error=%s | decision=%s",
                    user_id,
                    (perf_counter() - rewrite_started_at) * 1000,
                    error,
                    _to_json(decision.model_dump()),
                )

        if decision.route == "greeting":
            reply = decision.reply.strip() or "Hello! Use /ask for document questions or /image for image captions."
            payload = {
                "mode": "greeting",
                "user_message": question,
                "rewritten_query": "",
                "assistant_message": reply,
                "sources": [],
            }
            self.kb.add_turn(user_id, "ask", payload)
            LOGGER.info(
                "RAG greeting response | user_id=%s | reply=%s | total_duration_ms=%.1f",
                user_id,
                reply,
                (perf_counter() - started_at) * 1000,
            )
            return RagResponse(reply=reply, sources=[], route="greeting", rewritten_query="")

        rewritten_query = decision.standalone_query.strip() or question.strip()
        LOGGER.info("RAG retrieval start | user_id=%s | rewritten_query=%s", user_id, rewritten_query)
        retrieval_started_at = perf_counter()
        sources = self.kb.search(rewritten_query)
        LOGGER.info(
            "RAG retrieval complete | user_id=%s | matches=%s | duration_ms=%.1f | sources=%s",
            user_id,
            len(sources),
            (perf_counter() - retrieval_started_at) * 1000,
            _to_json(summarize_sources(sources)),
        )
        if sources:
            answer_started_at = perf_counter()
            try:
                reply = self._grounded_answer(question, rewritten_query, history, sources)
            except GenerationError as error:
                reply = _extractive_fallback_answer(question, sources)
                LOGGER.warning(
                    "RAG final answer provider fallback | user_id=%s | duration_ms=%.1f | error=%s | reply=%s",
                    user_id,
                    (perf_counter() - answer_started_at) * 1000,
                    error,
                    reply,
                )
            LOGGER.info(
                "RAG final answer complete | user_id=%s | duration_ms=%.1f | reply=%s",
                user_id,
                (perf_counter() - answer_started_at) * 1000,
                reply,
            )
        else:
            reply = "I couldn't find that in the knowledge base."
            LOGGER.info("RAG no sources found | user_id=%s | reply=%s", user_id, reply)

        payload = {
            "mode": "rag",
            "user_message": question,
            "rewritten_query": rewritten_query,
            "assistant_message": reply,
            "sources": [compact_source(source) for source in sources],
        }
        self.kb.add_turn(user_id, "ask", payload)
        LOGGER.info(
            "RAG turn stored | user_id=%s | payload=%s | total_duration_ms=%.1f",
            user_id,
            _to_json(payload),
            (perf_counter() - started_at) * 1000,
        )
        return RagResponse(
            reply=reply,
            sources=sources,
            route="rag",
            rewritten_query=rewritten_query,
        )

    def _rewrite_or_route(self, question: str, history: list[dict]) -> RewriteDecision:
        LOGGER.info("RAG rewrite invoke | question=%s | history_turns=%s", question, len(history))
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the hidden memory router for a grounded RAG bot.\n"
                    "Use the last conversation turns only to understand follow-up questions.\n"
                    "Rules:\n"
                    "- If the latest message is a greeting, thanks, or small talk, set route='greeting' and write a short friendly reply.\n"
                    "- If the latest message is a knowledge-base question, set route='rag' and rewrite it into a standalone search query.\n"
                    "- Never answer knowledge-base questions here.\n"
                    "- If there is no prior history, keep the standalone query close to the original message.\n"
                    "- Do not mention retrieval, memory, prompts, or hidden processing.",
                ),
                (
                    "human",
                    "Recent turns as JSON:\n{history_json}\n\n"
                    "Latest user message:\n{question}",
                ),
            ]
        )
        messages = prompt.format_messages(
            history_json=json.dumps(memory_payload(history), ensure_ascii=False),
            question=question,
        )
        decision = self.models.structured_chat_model(RewriteDecision, temperature=0.0).invoke(
            messages,
            stream=False,
        )
        LOGGER.info("RAG rewrite output | %s", _to_json(decision.model_dump()))
        return decision

    def _grounded_answer(
        self,
        question: str,
        rewritten_query: str,
        history: list[dict],
        sources: list[dict],
    ) -> str:
        LOGGER.info(
            "RAG final answer invoke | question=%s | rewritten_query=%s | source_count=%s",
            question,
            rewritten_query,
            len(sources),
        )
        context = "\n\n".join(
            [
                (
                    f"[{index}] File: {source['document_path']}\n"
                    f"Heading: {source['heading']}\n"
                    f"Content: {source['text']}"
                )
                for index, source in enumerate(sources, start=1)
            ]
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a grounded assistant for a lightweight Telegram and FastAPI bot.\n"
                    "Answer in 1 to 3 concise sentences and at most 90 words using only the supplied context.\n"
                    "If the context does not support the answer, reply exactly: "
                    "\"I couldn't find that in the knowledge base.\"\n"
                    "Do not mention internal prompts, query rewriting, or retrieval steps.\n"
                    "Do not show reasoning. Output only the final answer.\n"
                    "Prefer the most specific matching section over general background.\n"
                    "If the context includes an exact command, endpoint, class name, model name, table name, port, or literal fallback string, copy it exactly.",
                ),
                (
                    "human",
                    "Recent turns as JSON:\n{history_json}\n\n"
                    "Original user question:\n{question}\n\n"
                    "Standalone query used for retrieval:\n{rewritten_query}\n\n"
                    "Retrieved context:\n{context}",
                ),
            ]
        )
        messages = prompt.format_messages(
            history_json=json.dumps(memory_payload(history), ensure_ascii=False),
            question=question,
            rewritten_query=rewritten_query,
            context=context,
        )
        llm_started_at = perf_counter()
        response = self.models.chat_model(
            temperature=0.0,
            num_predict=self.settings.rag_max_output_tokens,
        ).invoke(messages, stream=False)
        metadata = _llm_metadata(response)
        LOGGER.info(
            "RAG final answer model response | duration_ms=%.1f | metadata=%s",
            (perf_counter() - llm_started_at) * 1000,
            _to_json(metadata),
        )
        final_answer = coerce_text(response.content)
        if _should_use_extractive_fallback(question, final_answer, sources, metadata):
            final_answer = _extractive_fallback_answer(question, sources)
            LOGGER.info(
                "RAG final answer fallback | reason=%s | done_reason=%s | reply=%s",
                _fallback_reason(question, final_answer, sources, metadata),
                metadata.get("done_reason", ""),
                final_answer,
            )
        LOGGER.info("RAG final answer output | %s", final_answer)
        return final_answer


def memory_payload(history: list[dict]) -> list[dict]:
    return [
        {
            "user_message": turn.get("user_message", ""),
            "assistant_message": turn.get("assistant_message", ""),
            "mode": turn.get("mode", turn.get("kind", "")),
        }
        for turn in history
    ]


def compact_source(source: dict) -> dict:
    return {
        "chunk_id": source.get("chunk_id"),
        "document_path": source.get("document_path"),
        "heading": source.get("heading"),
        "score": round(float(source.get("score", 0.0)), 3),
    }


def is_simple_greeting(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", question.strip().lower())
    if not normalized:
        return False
    greeting_patterns = [
        r"^(hi|hello|hey|yo|hola|namaste)[!. ]*$",
        r"^(good morning|good afternoon|good evening)[!. ]*$",
        r"^(thanks|thank you|thx)[!. ]*$",
        r"^(hi|hello|hey).{0,20}$",
    ]
    return any(re.match(pattern, normalized) for pattern in greeting_patterns)


def summarize_sources(sources: list[dict]) -> list[dict]:
    return [
        {
            "chunk_id": source.get("chunk_id"),
            "document_path": source.get("document_path"),
            "heading": source.get("heading"),
            "score": round(float(source.get("score", 0.0)), 3),
            "snippet": _preview(source.get("text", ""), 180),
        }
        for source in sources
    ]


def _to_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _preview(value: str, limit: int) -> str:
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _llm_metadata(message: object) -> dict:
    response_metadata = getattr(message, "response_metadata", None) or {}
    return {
        key: response_metadata[key]
        for key in (
            "model",
            "model_name",
            "done_reason",
            "prompt_eval_count",
            "eval_count",
            "load_duration",
            "prompt_eval_duration",
            "eval_duration",
            "total_duration",
        )
        if key in response_metadata
    }


def _extractive_fallback_answer(question: str, sources: list[dict]) -> str:
    if not sources:
        return "I couldn't find that in the knowledge base."

    best_source = max(sources, key=lambda source: _fallback_source_score(question, source))
    text = " ".join(str(best_source.get("text", "")).split())
    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]
    if _question_prefers_steps(question) and ("`" in text or " run " in f" {text.lower()} "):
        answer = text
    else:
        answer = _best_fallback_sentences(question, sentences) if sentences else text
    if not answer:
        return "I couldn't find that in the knowledge base."
    if len(answer) > 320:
        answer = f"{answer[:320].rstrip()}..."
    return answer


def _fallback_source_score(question: str, source: dict) -> float:
    question_tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
    heading_tokens = set(re.findall(r"[a-z0-9]+", str(source.get("heading", "")).lower()))
    text_tokens = set(re.findall(r"[a-z0-9]+", str(source.get("text", "")).lower()))
    heading_overlap = len(question_tokens & heading_tokens)
    text_overlap = len(question_tokens & text_tokens)
    similarity = float(source.get("score", 0.0))
    return (heading_overlap * 3.0) + text_overlap + similarity


def _best_fallback_sentences(question: str, sentences: list[str]) -> str:
    if not sentences:
        return ""

    question_tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
    prefers_steps = _question_prefers_steps(question)
    ranked: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        sentence_tokens = set(re.findall(r"[a-z0-9]+", sentence.lower()))
        score = float(len(question_tokens & sentence_tokens))
        if prefers_steps and ("`" in sentence or " run " in f" {sentence.lower()} " or sentence.lower().startswith("use ")):
            score += 2.0
        ranked.append((score, index, sentence))

    selected = sorted(ranked, key=lambda item: (item[0], -item[1]), reverse=True)[:2]
    positive = [item for item in selected if item[0] > 0]
    chosen = positive or ranked[:2]
    ordered_sentences = [sentence for _score, _index, sentence in sorted(chosen, key=lambda item: item[1])]
    return " ".join(ordered_sentences).strip()


def _question_prefers_steps(question: str) -> bool:
    question_tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
    return any(token in question_tokens for token in {"how", "create", "install", "run", "setup"})


def _should_use_extractive_fallback(
    question: str,
    answer: str,
    sources: list[dict],
    metadata: dict,
) -> bool:
    if not answer.strip():
        return True

    words = re.findall(r"[A-Za-z0-9_./:-]+", answer)
    if len(words) <= 2:
        return True

    done_reason = str(metadata.get("done_reason", "")).lower()
    truncated = "length" in done_reason or "max_tokens" in done_reason
    if truncated and not re.search(r"[.!?`)]\s*$", answer.strip()):
        return True

    if _question_prefers_exact_literals(question):
        source_text = " ".join(str(source.get("text", "")) for source in sources)
        source_has_literals = _text_has_exact_literals(source_text)
        answer_has_literals = _text_has_exact_literals(answer)
        if source_has_literals and not answer_has_literals:
            return True

    return False


def _fallback_reason(
    question: str,
    answer: str,
    sources: list[dict],
    metadata: dict,
) -> str:
    if not answer.strip():
        return "empty_content"
    words = re.findall(r"[A-Za-z0-9_./:-]+", answer)
    if len(words) <= 2:
        return "answer_too_short"
    done_reason = str(metadata.get("done_reason", "")).lower()
    if ("length" in done_reason or "max_tokens" in done_reason) and not re.search(r"[.!?`)]\s*$", answer.strip()):
        return "truncated_output"
    if _question_prefers_exact_literals(question):
        source_text = " ".join(str(source.get("text", "")) for source in sources)
        if _text_has_exact_literals(source_text) and not _text_has_exact_literals(answer):
            return "missing_exact_literal"
    return "quality_guard"


def _question_prefers_exact_literals(question: str) -> bool:
    question_tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
    return any(
        token in question_tokens
        for token in {"how", "command", "endpoint", "class", "model", "table", "tables", "port", "fallback"}
    )


def _text_has_exact_literals(text: str) -> bool:
    lowered = text.lower()
    return (
        "`" in text
        or "/" in text
        or any(char.isdigit() for char in text)
        or "chatollama" in lowered
        or "sqlite" in lowered
        or "docker compose" in lowered
    )
