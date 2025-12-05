from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from src.agents.base import ConversationLog
from src.agents.customer_data_agent import CustomerDataAgent


class SupportAgent:
    """Handles support reasoning and may request more context from data agent."""

    def __init__(self, data_agent: CustomerDataAgent, log: ConversationLog) -> None:
        self.data_agent = data_agent
        self.log = log
        self.name = "Support"

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
        return f"{prefix}Support response for {label}: {issue}.{context_note}"

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
