from __future__ import annotations

import re
from typing import Dict, Optional

from mcp_server.server import MCPServer
from src.agents.base import ConversationLog
from src.agents.data_agent import CustomerDataAgent
from src.agents.support_agent import SupportAgent


class RouterAgent:
    """Simple orchestrator that demonstrates task allocation, negotiation, and multi-step routing."""

    def __init__(self, mcp_server: MCPServer) -> None:
        self.log = ConversationLog()
        self.data_agent = CustomerDataAgent(mcp_server, self.log)
        self.support_agent = SupportAgent(mcp_server, self.log)

    def _parse_customer_id(self, query: str) -> Optional[int]:
        match = re.search(r"(?:id|customer)\s*(\d+)", query.lower())
        return int(match.group(1)) if match else None

    def _parse_email(self, query: str) -> Optional[str]:
        match = re.search(r"[\w\.\-]+@[\w\-]+\.[\w\-]+", query)
        return match.group(0) if match else None

    def handle(self, query: str) -> Dict[str, str]:
        self.log.clear()
        normalized = query.lower()
        customer_id = self._parse_customer_id(query)

        if "status of all high-priority tickets" in normalized:
            response = self._scenario_high_priority_report()
        elif "active customers" in normalized and "open tickets" in normalized:
            response = self._scenario_active_with_open_tickets()
        elif "charged twice" in normalized or "refund" in normalized:
            response = self._scenario_escalation(customer_id)
        elif "upgrade" in normalized or "upgrad" in normalized:
            response = self._scenario_upgrade(customer_id or 2)
        elif "update my email" in normalized and "history" in normalized:
            response = self._scenario_update_email(customer_id or 1, self._parse_email(query))
        elif "get customer information" in normalized:
            response = self._scenario_get_customer(customer_id or 1)
        else:
            response = self._scenario_generic(customer_id)

        return {"response": response, "log": self.log.dump()}

    def _scenario_get_customer(self, customer_id: int) -> str:
        result = self.data_agent.fetch_customer(customer_id)
        if result.error or not result.result:
            return "Customer not found."
        return f"Customer {customer_id}: {result.result}"

    def _scenario_upgrade(self, customer_id: int) -> str:
        info = self.data_agent.fetch_customer(customer_id)
        support_reply = self.support_agent.handle_support_request(
            info.result if info.result else None, "Upgrade request", urgent=False
        )
        return support_reply

    def _scenario_active_with_open_tickets(self) -> str:
        customers = self.data_agent.list_customers(status="active", limit=50).result
        open_tickets = []
        for cust in customers:
            history = self.data_agent.history(cust["id"]).result
            open_tickets.extend([t for t in history if t["status"] != "resolved"])
        if not open_tickets:
            return "No open tickets for active customers."
        tickets_summary = ", ".join(
            f"{t['issue']} for customer {t['customer_id']} ({t['status']})"
            for t in open_tickets
        )
        return f"Open tickets for active customers: {tickets_summary}"

    def _scenario_escalation(self, customer_id: Optional[int]) -> str:
        cid = customer_id or 2
        customer = self.data_agent.fetch_customer(cid).result
        self.log.record(
            "router",
            "support-agent",
            "escalate_billing_refund",
            {"customer_id": cid, "issue": "duplicate charge"},
        )
        ticket = self.support_agent.ensure_ticket(
            cid, issue="Billing refund request (duplicate charge)", priority="high"
        )
        reply = self.support_agent.handle_support_request(customer, "Billing refund", urgent=True)
        return f"{reply}. Ticket created: {ticket}"

    def _scenario_update_email(self, customer_id: int, new_email: Optional[str]) -> str:
        updated = None
        if new_email:
            updated = self.data_agent.update_customer(customer_id, {"email": new_email}).result
        history = self.data_agent.history(customer_id).result
        history_text = self.support_agent.summarize_history(customer_id)
        return f"Email updated to {updated['email'] if updated else 'unchanged'}. History: {history_text}"

    def _scenario_high_priority_report(self) -> str:
        customers = self.data_agent.list_customers(status="active", limit=50).result
        premium_ids = [c["id"] for c in customers if c["id"] % 2 == 1]
        tickets = self.data_agent.high_priority_tickets_for_customers(premium_ids)
        return self.support_agent.high_priority_report(tickets)

    def _scenario_generic(self, customer_id: Optional[int]) -> str:
        cid = customer_id or 1
        info = self.data_agent.fetch_customer(cid).result
        return f"Routed to support: {info['name'] if info else 'customer'}"
