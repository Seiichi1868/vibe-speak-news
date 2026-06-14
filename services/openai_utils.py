import json
import re

from openai import OpenAI

PREMIUM_MAX_COMPLETION_TOKENS = 4096
PREMIUM_REASONING_EFFORT = "low"


def parse_json_object(raw: str) -> dict:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("Expected JSON object", text, 0)
    return data


def extract_completion_text(completion) -> str:
    if not completion.choices:
        return ""
    message = completion.choices[0].message
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            else:
                text = getattr(part, "text", None)
                if text:
                    parts.append(str(text))
        return "".join(parts).strip()
    return str(content or "").strip()


def is_reasoning_chat_model(model: str) -> bool:
    name = (model or "").strip().lower()
    if name.startswith("gpt-5") and "chat" not in name:
        return True
    return name.startswith(("o1", "o3", "o4"))


def reasoning_effort_for_model(model: str) -> str | None:
    name = (model or "").strip().lower()
    if not is_reasoning_chat_model(model):
        return None
    if name.startswith("gpt-5.4") or name.startswith("gpt-5.1"):
        return "none"
    return PREMIUM_REASONING_EFFORT


def create_json_chat_completion(
    client: OpenAI,
    model: str,
    messages: list,
    *,
    temperature: float = 0.3,
) -> dict:
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if is_reasoning_chat_model(model):
        kwargs["max_completion_tokens"] = PREMIUM_MAX_COMPLETION_TOKENS
        effort = reasoning_effort_for_model(model)
        if effort:
            kwargs["reasoning_effort"] = effort
    else:
        kwargs["temperature"] = temperature

    completion = client.chat.completions.create(**kwargs)
    raw = extract_completion_text(completion)
    if not raw:
        finish_reason = ""
        if completion.choices:
            finish_reason = str(completion.choices[0].finish_reason or "")
        raise ValueError(f"AI からの応答が空でした (finish_reason={finish_reason or 'unknown'})")
    return parse_json_object(raw)
