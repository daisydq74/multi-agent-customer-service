from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

from src.agents.base import ConversationLog
from src.agents.customer_data_agent import CustomerDataAgent
from src.llm.openai_chat_llm import OpenAIChatLLM, has_api_key


class SupportAgent:
    """Handles support reasoning and may request more context from data agent."""

    def __init__(self, data_agent: CustomerDataAgent, log: ConversationLog) -> None:
        if not has_api_key():
            raise RuntimeError("Missing OPENAI_API_KEY (LLM routing is required).")
        self.data_agent = data_agent
        self.log = log
        self.name = "Support"
        self.temperature = float(
            os.getenv("OPENAI_TEMPERATURE_SUPPORT")
            or os.getenv("OPENAI_TEMPERATURE")
            or 0
        )
        self.max_tokens = int(
            os.getenv("OPENAI_MAX_TOKENS_SUPPORT")
            or os.getenv("OPENAI_MAX_TOKENS")
            or 300
        )
        model = (
            os.getenv("OPENAI_MODEL_SUPPORT")
            or os.getenv("OPENAI_MODEL")
            or "gpt-4o-mini"
        )
        self.llm = OpenAIChatLLM(
            model_env_var="OPENAI_MODEL_SUPPORT",
            default_model=model,
            model=model,
        )
        self.model = model

    async def handle_support(
        self,
        customer: Optional[Dict[str, Any]],
        issue: str,
        urgent: bool = False,
        needs_context: bool = False,
    ) -> str:
        self.llm.last_used = False
        history_result = None
        if needs_context and customer:
            self.log.record(
                self.name, "CustomerData", "request_context", {"customer_id": customer["id"]}
            )
            history = await self.data_agent.history(customer["id"], sender=self.name)
            history_result = history.result

        context: Dict[str, Any] = {
            "user_query": issue,
            "customer": customer,
            "history": history_result,
            "urgent": urgent,
            "needs_context": needs_context,
        }
        return await self.draft_response(context)

    async def ensure_ticket(self, customer_id: int, issue: str, priority: str = "medium") -> Dict[str, Any]:
        result = await self.data_agent.create_ticket(
            customer_id, issue, priority=priority, sender=self.name
        )
        return result.result

    async def summarize_history(self, customer_id: int) -> str:
        history = await self.data_agent.history(customer_id, sender=self.name)
        if history.error or not history.result:
            return "No ticket history yet."
        return "; ".join(
            f"[{t['created_at']}] {t['issue']} ({t['status']}, {t['priority']})"
            for t in history.result
        )

    async def draft_response(self, context: Dict[str, Any]) -> str:
        """LLM-backed support reply used by the router plan."""

        self.llm.last_used = False

        system_prompt = (
            "You are a helpful customer support agent. Craft concise, empathetic replies that"
            " address the user's issue using any provided customer profile and history."
        )
        customer = context.get("customer")
        history = context.get("history")
        extra_context = []
        if customer:
            extra_context.append(f"Customer profile: {customer}")
        if history:
            extra_context.append(f"History: {history}")
        if context.get("ticket_updates"):
            extra_context.append(f"Ticket updates: {context.get('ticket_updates')}")
        tone = context.get("tone") or ("urgent" if context.get("urgent") else "standard")
        user_prompt = "\n".join(
            [
                f"User request: {context.get('user_query', '')}",
                f"Tone: {tone}",
                "Additional context: " + ("; ".join(extra_context) if extra_context else "none"),
                "Return only the response text, no JSON or commentary.",
            ]
        )

        try:
            reply = await asyncio.to_thread(
                self.llm.generate,
                system_prompt,
                user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return reply.strip() or self._fallback_response(context)
        except Exception:
            return self._fallback_response(context)

    def llm_meta(self, used_llm: bool) -> Dict[str, Any]:
        if used_llm:
            return {
                "used_llm": True,
                "model": self.model,
                "temperature": self.temperature,
            }
        return {"used_llm": False, "model": "none", "temperature": "none"}

    def _fallback_response(self, context: Dict[str, Any]) -> str:
        customer = context.get("customer")
        prefix = "URGENT: " if context.get("urgent") else ""
        label = f"{customer['name']} (id={customer['id']})" if customer else "customer"
        issue = context.get("user_query") or "Support request"
        history = context.get("history")
        if history:
            context_note = f" Context: {history}"
        elif context.get("needs_context"):
            context_note = " No prior tickets."
        else:
            context_note = ""
        return f"{prefix}Support response for {label}: {issue}.{context_note}"
