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

    async def draft_response(
        self,
        intent: str,
        tone: str = "helpful",
        urgency: str = "normal",
        customer: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> str:
        args = {
            "intent": intent,
            "tone": tone,
            "urgency": urgency,
            "customer_id": customer.get("id") if isinstance(customer, dict) else None,
            "notes": notes,
        }
        self.log.record("Router", self.name, "draft_response", args)

        prefix = "URGENT: " if urgency.lower() == "high" else ""
        tone_label = f"[{tone}] " if tone else ""

        if intent == "customer_info":
            if not customer:
                return f"{prefix}{tone_label}I can look up the account, but I need the customer ID first."
            name = customer.get("name", "customer")
            email = customer.get("email")
            status = customer.get("status", "unknown")
            return f"{prefix}{tone_label}{name} (id={customer.get('id')}), status={status}, email={email}."

        if intent == "upgrade":
            if not customer:
                return f"{prefix}{tone_label}Happy to help upgrade your account. Please share your customer ID so I can pull your plan details."
            history = (data or {}).get("history") or []
            history_note = (
                " Recent tickets: "
                + "; ".join(f"{h['issue']} ({h['status']})" for h in history[:3])
                if history
                else ""
            )
            return (
                f"{prefix}{tone_label}Hi {customer.get('name')}, I can help upgrade your account. "
                "I'll review your plan, confirm billing, and process the upgrade—please confirm the tier you want." + history_note
            )

        if intent == "list_open_tickets":
            customers = ((data or {}).get("customers") or []) if isinstance(data, dict) else []
            if not customers:
                return f"{prefix}{tone_label}No active customers with open tickets right now."
            lines = []
            for cust in customers:
                tickets = cust.get("open_tickets", [])
                ticket_summary = ", ".join(
                    f"#{t['ticket_id']} ({t['status']}, {t['priority']}): {t['issue']}" for t in tickets
                )
                lines.append(
                    f"{cust.get('name')} (id={cust.get('customer_id')}, status={cust.get('status')}): {ticket_summary}"
                )
            return prefix + tone_label + "; ".join(lines)

        if intent == "refund":
            if not customer:
                return (
                    f"{prefix}{tone_label}I see this is urgent. Please share your customer ID or email so I can verify the account, "
                    "stop any duplicate charges, and initiate the refund."
                )
            return (
                f"{prefix}{tone_label}I've flagged your account (id={customer.get('id')}) for a duplicate-charge refund. "
                "I'm creating a high-priority ticket and will process the refund once I confirm the transaction details."
            )

        if intent == "multi_intent_update_history":
            if not customer or not customer.get("id"):
                return (
                    f"{prefix}{tone_label}I can update your email and pull your ticket history. "
                    "Please provide your customer ID so I can proceed with both steps."
                )
            updated = (data or {}).get("updated")
            history = (data or {}).get("history") or []
            update_msg = (
                f"Email updated to {updated.get('email')}" if isinstance(updated, dict) and updated.get("email") else "Email update pending"
            )
            history_msg = (
                "; ".join(f"#{t['id']} {t['issue']} ({t['status']})" for t in history)
                if history
                else "No ticket history yet."
            )
            return f"{prefix}{tone_label}{update_msg}. Ticket history: {history_msg}."

        return f"{prefix}{tone_label}How can I help?"

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
