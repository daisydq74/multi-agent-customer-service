from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from openai import OpenAI


def has_api_key() -> bool:
    """Return True if an OpenAI API key is configured."""

    return bool(os.environ.get("OPENAI_API_KEY"))


def safe_json_loads(text: str) -> Any:
    """Parse JSON responses, attempting to salvage the first JSON object if needed."""

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


class OpenAIChatLLM:
    """Lightweight wrapper around the OpenAI Chat Completions API."""

    def __init__(
        self,
        model_env_var: Optional[str] = None,
        default_model: str = "gpt-4o-mini",
        model: Optional[str] = None,
    ) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY")
        env_model = os.environ.get(model_env_var) if model_env_var else None
        self.model = model or env_model or default_model
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.last_used: bool = False

    def generate(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 300,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        self.last_used = False
        if not self.client:
            raise RuntimeError("OpenAI client unavailable; missing API key")

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        response = self.client.chat.completions.create(**kwargs)
        self.last_used = True
        return response.choices[0].message.content or ""
