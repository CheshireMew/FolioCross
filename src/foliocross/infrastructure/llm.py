"""OpenAI-compatible and deterministic fake model clients."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from ..domain.models import ModelProfile
from ..errors import FolioCrossError
from .credentials import CredentialStore


def is_transport_error(error: Exception) -> bool:
    from openai import APIConnectionError

    # APITimeoutError inherits APIConnectionError, not built-in TimeoutError.
    return isinstance(error, (APIConnectionError, TimeoutError, ConnectionError))


@dataclass(slots=True)
class ModelUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0


@dataclass(slots=True)
class ModelResponse:
    content: str
    usage: ModelUsage


def _value(obj: Any, name: str, default: int = 0) -> int:
    if isinstance(obj, dict):
        raw = obj.get(name, default)
    else:
        raw = getattr(obj, name, default)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return default


class OpenAICompatibleClient:
    def __init__(
        self, profile: ModelProfile, credential_store: CredentialStore | None = None
    ) -> None:
        self.profile = profile
        self.credentials = credential_store or CredentialStore()
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as error:
            raise FolioCrossError(
                "dependency_missing", "缺少 openai 包，请先同步项目依赖。"
            ) from error
        key = self.credentials.get(self.profile.id, self.profile.api_key_env)
        if not key and self.profile.provider not in {"ollama", "vllm", "fake"}:
            raise FolioCrossError(
                "api_key_missing",
                f"没有找到 {self.profile.name} 的 API Key。请在设置中填写，或设置 {self.profile.api_key_env}。",
            )
        self._client = OpenAI(
            api_key=key or "local-no-key",
            base_url=self.profile.base_url,
            timeout=600,
            max_retries=0,
        )
        return self._client

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        json_mode: bool = True,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        messages = [
            {"role": "system", "content": system + ("\n只输出有效 JSON。" if json_mode else "")},
            {"role": "user", "content": user + ("\n只输出有效 JSON。" if json_mode else "")},
        ]
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if self.profile.provider == "deepseek":
            kwargs["extra_body"] = {
                "thinking": {"type": "enabled" if self.profile.thinking else "disabled"}
            }
        response = self._ensure_client().chat.completions.create(**kwargs)
        if not response.choices:
            raise FolioCrossError("empty_response", "模型没有返回任何候选结果。")
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise FolioCrossError("empty_response", "模型返回了空内容。")
        usage = getattr(response, "usage", None)
        cache = _value(usage, "prompt_cache_hit_tokens")
        if not cache:
            details = getattr(usage, "prompt_tokens_details", None)
            cache = _value(details, "cached_tokens")
        return ModelResponse(
            content,
            ModelUsage(
                prompt_tokens=_value(usage, "prompt_tokens"),
                completion_tokens=_value(usage, "completion_tokens"),
                cache_hit_tokens=cache,
            ),
        )


class FakeClient:
    """Offline deterministic client used by tests and UI demonstrations."""

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        json_mode: bool = True,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del model, system, max_tokens
        delay = float(os.environ.get("FOLIOCROSS_FAKE_DELAY_SECONDS", "0") or 0)
        if delay > 0:
            time.sleep(delay)
        try:
            payload = json.loads(user[user.index("{") :])
        except (ValueError, json.JSONDecodeError):
            payload = {}
        if "review_segments" in payload:
            content = json.dumps({"issues": []}, ensure_ascii=False)
        elif "retranslate_source" in payload:
            content = json.dumps(
                {"translation": _fake_translation(str(payload["retranslate_source"]))},
                ensure_ascii=False,
            )
        elif "segments" in payload:
            content = json.dumps(
                {
                    "translations": [
                        _fake_translation(str(item["text"])) for item in payload["segments"]
                    ]
                },
                ensure_ascii=False,
            )
        elif "chapter_text" in payload:
            content = json.dumps({"summary": "离线章节梗概", "terms": []}, ensure_ascii=False)
        elif "chapter_summaries" in payload:
            content = json.dumps(
                {"overview": "离线全书概览", "style": "清晰、自然", "characters": []},
                ensure_ascii=False,
            )
        elif "target" in payload:
            content = json.dumps({"translation": payload["target"]}, ensure_ascii=False)
        else:
            content = "{}"
        return ModelResponse(
            content,
            ModelUsage(
                prompt_tokens=max(1, len(user) // 4), completion_tokens=max(1, len(content) // 2)
            ),
        )


def _fake_translation(text: str) -> str:
    marker = re.compile(r"⟦FC:[^⟧]+⟧")
    pieces = marker.split(text)
    tokens = marker.findall(text)
    result = ["【离线译文】"]
    for index, piece in enumerate(pieces):
        result.append("".join("译" if character.isalnum() else character for character in piece))
        if index < len(tokens):
            result.append(tokens[index])
    return "".join(result)


def parse_json_content(content: str) -> dict[str, Any]:
    value = content.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1])
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise FolioCrossError("invalid_json", f"模型没有返回有效 JSON：{error.msg}") from error
    if not isinstance(parsed, dict):
        raise FolioCrossError("invalid_json", "模型返回的 JSON 顶层必须是对象。")
    return parsed
