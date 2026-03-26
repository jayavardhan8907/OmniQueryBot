from __future__ import annotations

import json

from google import genai
from google.genai import types


class GenerationError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str, model_name: str) -> None:
        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)

    def answer_with_context(
        self,
        query: str,
        sources: list[dict],
        history: list[dict],
    ) -> str:
        history_lines = ["Recent conversation:"]
        if history:
            for turn in history:
                history_lines.append(f"User: {turn['user_input'][:240]}")
                history_lines.append(f"Bot: {turn['bot_output'][:240]}")
        else:
            history_lines.append("No prior turns.")

        context_lines = ["Knowledge base context:"]
        for index, source in enumerate(sources, start=1):
            context_lines.append(
                f"[{index}] File: {source['document_path']} | Heading: {source['heading']} | "
                f"Score: {source['score']:.3f}"
            )
            context_lines.append(source["text"])

        prompt = "\n".join(
            [
                *history_lines,
                "",
                *context_lines,
                "",
                f"User question: {query}",
                "",
                "Answer in 3 to 6 sentences. Use only the supplied context.",
            ]
        )
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                systemInstruction=(
                    "You are a grounded assistant. "
                    "If the context does not contain the answer, say: "
                    "\"I couldn't find that in the knowledge base.\""
                ),
                temperature=0.2,
                maxOutputTokens=300,
            ),
        )
        text = (response.text or "").strip()
        if not text:
            raise GenerationError("Gemini returned an empty answer.")
        return text

    def describe_image(self, image_bytes: bytes, mime_type: str) -> dict:
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[
                "Return strict JSON with keys caption and tags. "
                "caption must be one short sentence. "
                "tags must be an array of exactly 3 short lowercase strings.",
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                systemInstruction="You create short image captions for a Telegram bot.",
                temperature=0.3,
                maxOutputTokens=180,
                responseMimeType="application/json",
            ),
        )
        payload = _parse_json((response.text or "").strip())
        caption = str(payload.get("caption", "")).strip()
        raw_tags = payload.get("tags", [])
        if not caption or not isinstance(raw_tags, list):
            raise GenerationError("Gemini returned an invalid image description.")

        tags: list[str] = []
        for tag in raw_tags:
            normalized = str(tag).strip().lower()
            if normalized and normalized not in tags:
                tags.append(normalized)
            if len(tags) == 3:
                break

        if len(tags) != 3:
            raise GenerationError("Gemini did not return exactly 3 usable tags.")

        return {"caption": caption, "tags": tags}

    def summarize(self, artifact_type: str, artifact_text: str) -> str:
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=(
                f"Artifact type: {artifact_type}\n"
                "Summarize the following in 2 to 4 concise sentences.\n\n"
                f"{artifact_text}"
            ),
            config=types.GenerateContentConfig(
                systemInstruction="You write compact summaries for chat bots.",
                temperature=0.2,
                maxOutputTokens=220,
            ),
        )
        text = (response.text or "").strip()
        if not text:
            raise GenerationError("Gemini returned an empty summary.")
        return text


def _parse_json(raw_text: str) -> dict:
    if not raw_text:
        raise GenerationError("Gemini returned an empty JSON payload.")

    candidates = [raw_text]
    if "{" in raw_text and "}" in raw_text:
        candidates.append(raw_text[raw_text.find("{") : raw_text.rfind("}") + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise GenerationError("Gemini returned malformed JSON.")
