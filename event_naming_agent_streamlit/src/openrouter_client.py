from __future__ import annotations

import json
import re
from typing import Any

import requests


class OpenRouterError(RuntimeError):
    pass


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        raise OpenRouterError("Модель вернула пустой ответ. Повторите запрос или выберите другую бесплатную модель.")
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                value = part.get("text") or part.get("content")
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, dict) and isinstance(value.get("value"), str):
                    parts.append(value["value"])
        if parts:
            return "\n".join(parts)
        raise OpenRouterError("Модель вернула ответ без текстового JSON. Повторите запрос или выберите другую модель.")
    raise OpenRouterError(f"Модель вернула неподдерживаемый формат ответа: {type(content).__name__}")


def _extract_json(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    cleaned = _content_to_text(content).strip()
    if not cleaned:
        raise OpenRouterError("Модель вернула пустой ответ. Повторите запрос или выберите другую бесплатную модель.")
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise OpenRouterError("Модель вернула повреждённый JSON. Повторите запрос.") from exc
        raise OpenRouterError("Модель не вернула корректный JSON")


def call_openrouter(*, api_key: str, model: str, system_prompt: str, user_prompt: str, schema: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    if not api_key:
        raise OpenRouterError("Не настроен OPENROUTER_API_KEY")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt + "\n\nJSON SCHEMA:\n" + json.dumps(schema, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "event_naming_response", "strict": True, "schema": schema},
        },
    }
    def send(body: dict[str, Any]):
        return requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://streamlit.app", "X-Title": "Event Naming Agent"},
            json=body,
            timeout=timeout,
        )

    try:
        response = send(payload)
    except requests.RequestException as exc:
        raise OpenRouterError(f"Не удалось связаться с OpenRouter: {exc}") from exc
    if response.status_code == 400 and "response_format" in response.text.lower():
        fallback = dict(payload)
        fallback["response_format"] = {"type": "json_object"}
        try:
            response = send(fallback)
        except requests.RequestException as exc:
            raise OpenRouterError(f"Не удалось повторить запрос к OpenRouter: {exc}") from exc
    if response.status_code == 429:
        raise OpenRouterError("Исчерпан лимит бесплатной модели OpenRouter. Повторите позже.")
    if not response.ok:
        detail = response.text[:500]
        raise OpenRouterError(f"OpenRouter вернул ошибку {response.status_code}: {detail}")
    try:
        data = response.json()
    except ValueError as exc:
        raise OpenRouterError("OpenRouter вернул ответ в неизвестном формате. Повторите запрос.") from exc
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError("Ответ OpenRouter не содержит результата модели") from exc
    if isinstance(message.get("parsed"), dict):
        return message["parsed"]
    content = message.get("content")
    if content is None and message.get("refusal"):
        raise OpenRouterError("Модель отказалась обработать запрос. Проверьте, что БТ содержит только обезличенные учебные данные.")
    return _extract_json(content)

