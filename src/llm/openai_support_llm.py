from __future__ import annotations

import os
from typing import Optional

from openai import OpenAI


class OpenAISupportLLM:
    """Small wrapper around OpenAI chat completions for support responses."""

    def __init__(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY must be set for OpenAISupportLLM")

        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.temperature = float(os.environ.get("OPENAI_TEMPERATURE", "0.2"))
        self.max_tokens = int(os.environ.get("OPENAI_MAX_TOKENS", "256"))
        self.client = OpenAI(api_key=api_key)

    def generate(self, user_text: str, context: Optional[str] = None) -> str:
        context_block = context.strip() if context else "No additional context provided."
        system_prompt = (
            "You are a helpful SaaS customer support agent. "
            "Use the provided customer details and context to craft a concise, clear reply. "
            "Never claim that a refund has already been issued, a database has been updated, or any action is already complete. "
            "If the next step requires fetching data, creating/updating tickets, or confirming details, explicitly tell the customer what will happen next or what you need. "
            "Keep the response focused on the request and next actions, without unnecessary flourishes."
        )
        user_prompt = (
            f"Customer message: {user_text}\n"
            f"Context: {context_block}\n"
            "Provide the next support reply, following the constraints above."
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        return response.choices[0].message.content.strip()
