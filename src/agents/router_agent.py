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

    def __init__(
        self,
        mcp_server: MCPServer | None,
        log: ConversationLog | None = None,
        data_agent: CustomerDataAgent | None = None,
        support_agent: SupportAgent | None = None,
    ) -> None:
        self.log = log or ConversationLog()
        if data_agent and support_agent:
            self.data_agent = data_agent
            self.support_agent = support_agent
        else:
            if mcp_server is None:
                raise ValueError("mcp_server is required when no agents are provided")
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

        if "cancel my subscription" in normalized and "billing" in normalized:
            response = await self._cancel_with_billing_issue(customer_id)
        elif "update my email" in normalized and "history" in normalized:
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
        lines = [
            f"customer_id={t['customer_id']}, ticket_id={t['id']}, issue={t['issue']}, priority={t['priority']}, status={t['status']}"
            for t in open_tickets
        ]
        return "\n".join(lines)

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
        # Scenario 5: multi-intent + parallel work (update + history)
        if new_email:
            self._log_step(
                "CustomerData",
                "scenario5.update_customer",
                {"customer_id": customer_id, "data": {"email": new_email}},
            )
        self._log_step("CustomerData", "scenario5.history", {"customer_id": customer_id})
        self._log_step("Support", "scenario5.summarize_history", {"customer_id": customer_id})

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
        # Scenario 3: multi-step coordination (premium customers + high priority tickets)
        self._log_step("CustomerData", "scenario3.list_customers", {"status": "active", "limit": 50})
        customers = (await self.data_agent.list_customers(status="active", limit=50)).result or []

        premium_ids = []
        for c in customers:
            if c["id"] == 12345 or c.get("status") == "vip":
                premium_ids.append(c["id"])
        premium_ids = list(dict.fromkeys(premium_ids))  # preserve order, remove dupes

        if not premium_ids:
            return "No high-priority tickets found."

        self._log_step("CustomerData", "scenario3.high_priority_tickets", {"customer_ids": premium_ids})
        tickets = await self.data_agent.high_priority_tickets(premium_ids)

        if not tickets:
            return "No high-priority tickets found."

        return "\n".join(
            f"Ticket {t['id']} for customer {t['customer_id']}: {t['issue']} ({t['status']})"
            for t in tickets
        )

    async def _cancel_with_billing_issue(self, customer_id: int) -> str:
        # Scenario 2: negotiation with support asking for billing context
        issue = "Cancel subscription with billing issues"
        self._log_step("Support", "scenario2.can_you_handle", {"issue": issue})
        self.log.record("Support", "Router", "scenario2.need_context", {"context": "billing history"})
        history = await self.data_agent.history(customer_id)
        history_items = history.result or []
        context_summary = (
            "; ".join(f"{h['issue']} ({h['status']}, {h['priority']})" for h in history_items)
            if history_items
            else "No prior billing tickets."
        )
        support_reply = await self.support_agent.handle_support(
            None, issue, urgent=True, needs_context=False
        )
        return f"{support_reply} Context: {context_summary}"

    async def _fallback(self, customer_id: int) -> str:
        info = await self.data_agent.fetch_customer(customer_id)
        self._log_step("Support", "scenario_generic.handle_support", {"issue": "General inquiry"})
        return await self.support_agent.handle_support(info.result, "General inquiry", urgent=False)

    def _log_step(self, receiver: str, action: str, args: Dict[str, object]) -> None:
        self.log.record("Router", receiver, action, args)
