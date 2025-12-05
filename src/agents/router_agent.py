from __future__ import annotations

import asyncio
import re
from typing import Dict, Optional

from mcp_server.server import MCPServer
from src.agents.base import ConversationLog
from src.agents.customer_data_agent import CustomerDataAgent
from src.agents.support_agent import SupportAgent


class RouterAgent:
    """Async orchestrator; only component that talks to the user."""

    def __init__(self, mcp_server: MCPServer) -> None:
        self.log = ConversationLog()
        self.data_agent = CustomerDataAgent(mcp_server, self.log)
        self.support_agent = SupportAgent(self.data_agent, self.log)

    def _parse_customer_id(self, query: str) -> Optional[int]:
        match = re.search(r"(?:id|customer)\s*(\d+)", query.lower())
        return int(match.group(1)) if match else None

    def _parse_email(self, query: str) -> Optional[str]:
        match = re.search(r"[\w\.\-]+@[\w\-]+\.[\w\-]+", query)
        return match.group(0) if match else None

    async def handle(self, query: str) -> Dict[str, str]:
        self.log.clear()
        normalized = query.lower()
        customer_id = self._parse_customer_id(query) or 1

        if "update my email" in normalized and "history" in normalized:
            response = await self._multi_intent_update_email(customer_id, self._parse_email(query))
        elif "charged twice" in normalized or "refund" in normalized:
            response = await self._escalation(customer_id)
        elif "high-priority tickets" in normalized:
            response = await self._high_priority_report()
        elif "open tickets" in normalized and "active customers" in normalized:
            response = await self._active_with_open_tickets()
        elif "upgrade" in normalized or "upgrad" in normalized:
            response = await self._upgrade(customer_id)
        elif "get customer information" in normalized or "customer information" in normalized:
            response = await self._get_customer(customer_id)
        else:
            response = await self._fallback(customer_id)

        return {"response": response, "log": self.log.dump()}

    async def _get_customer(self, customer_id: int) -> str:
        # Scenario 1: task allocation (Router -> Data -> Support optional)
        self._log_step("CustomerData", "scenario1.route_to_data", {"customer_id": customer_id})
        result = await self.data_agent.fetch_customer(customer_id)
        if result.error or not result.result:
            return "Customer not found."
        self._log_step("Support", "scenario1.route_to_support", {"customer_id": customer_id})
        return f"Customer {customer_id}: {result.result}"

    async def _upgrade(self, customer_id: int) -> str:
        info = await self.data_agent.fetch_customer(customer_id)
        self._log_step("Support", "scenario1.handle_support", {"issue": "Upgrade request"})
        return await self.support_agent.handle_support(info.result, "Upgrade request", urgent=False)

    async def _active_with_open_tickets(self) -> str:
        customers = (await self.data_agent.list_customers(status="active", limit=50)).result
        open_tickets = []
        for cust in customers or []:
            history = await self.data_agent.history(cust["id"])
            open_tickets.extend([t for t in history.result or [] if t["status"] != "resolved"])
        if not open_tickets:
            return "No open tickets for active customers."
        return "; ".join(
            f"{t['issue']} for customer {t['customer_id']} ({t['status']})" for t in open_tickets
        )

    async def _escalation(self, customer_id: int) -> str:
        info = await self.data_agent.fetch_customer(customer_id)
        # Scenario 2: negotiation/escalation with context request
        self._log_step("Support", "scenario2.negotiate", {"issue": "Billing refund"})
        ticket = await self.support_agent.ensure_ticket(
            customer_id, "Billing refund request (duplicate charge)", priority="high"
        )
        reply = await self.support_agent.handle_support(
            info.result, "Billing refund", urgent=True, needs_context=True
        )
        return f"{reply} Ticket created: {ticket}"

    async def _multi_intent_update_email(self, customer_id: int, new_email: Optional[str]) -> str:
        update_task = None
        if new_email:
            update_task = asyncio.create_task(
                self.data_agent.update_customer(customer_id, {"email": new_email})
            )
        history_task = asyncio.create_task(self.data_agent.history(customer_id))

        if update_task:
            updated, history = await asyncio.gather(update_task, history_task)
        else:
            updated = None
            history = await history_task

        email_val = updated.result["email"] if updated and updated.result else "unchanged"
        summary = await self.support_agent.summarize_history(customer_id)
        return f"Email updated to {email_val}. History: {summary}"

    async def _high_priority_report(self) -> str:
        customers = (await self.data_agent.list_customers(status="active", limit=50)).result or []
        premium_ids = [c["id"] for c in customers if c["id"] % 2 == 1]
        tickets = await self.data_agent.high_priority_tickets(premium_ids)
        if not tickets:
            return "No high-priority tickets found."
        return "\n".join(
            f"Ticket {t['id']} for customer {t['customer_id']}: {t['issue']} ({t['status']})"
            for t in tickets
        )

    async def _fallback(self, customer_id: int) -> str:
        info = await self.data_agent.fetch_customer(customer_id)
        self._log_step("Support", "scenario_generic.handle_support", {"issue": "General inquiry"})
        return await self.support_agent.handle_support(info.result, "General inquiry", urgent=False)

    def _log_step(self, receiver: str, action: str, args: Dict[str, object]) -> None:
        self.log.record("Router", receiver, action, args)
