from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.agents.base import ConversationLog
from src.agents.customer_data_agent import CustomerDataAgent

if TYPE_CHECKING:
    from src.llm.openai_support_llm import OpenAISupportLLM


class SupportAgent:
    """Handles support reasoning and may request more context from data agent."""

    def __init__(self, data_agent: CustomerDataAgent, log: ConversationLog) -> None:
        self.data_agent = data_agent
        self.log = log
        self.name = "Support"
        self._llm = self._maybe_init_llm()

    def _maybe_init_llm(self) -> Optional["OpenAISupportLLM"]:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        from src.llm.openai_support_llm import OpenAISupportLLM
        try:
            return OpenAISupportLLM()
        except Exception:
            return None

    async def handle_support(
        self,
        customer: Optional[Dict[str, Any]],
        issue: str,
        urgent: bool = False,
        needs_context: bool = False,
        ) -> str:
        if needs_context and customer:
            self.log.record(
                self.name, "CustomerData", "request_context", {"customer_id": customer["id"]}
            )
            history = await self.data_agent.history(customer["id"], sender=self.name)
            context_note = f" Context: {history.result}" if history.result else " No prior tickets."
        else:
            context_note = ""
        prefix = "URGENT: " if urgent else ""
        label = f"{customer['name']} (id={customer['id']})" if customer else "customer"
        rule_based = f"{prefix}Support response for {label}: {issue}.{context_note}"

        if not self._llm:
            return rule_based

        context_block = context_note.strip() if context_note else "No prior context provided."
        customer_summary = (
            f"{label}; email={customer.get('email')} status={customer.get('status')}"
            if customer
            else "Unknown customer"
        )
        prompt_issue = f"{prefix}{issue}"
        try:
            return self._llm.generate(
                user_text=f"Issue: {prompt_issue} | Customer: {customer_summary}",
                context=context_block,
            )
        except Exception:
            return rule_based

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
