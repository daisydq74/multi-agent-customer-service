from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

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
        self.system_prompt: str = """
You are the RouterAgent. Plan steps using only the allowed tools below.
- customer_data: get_customer, list_customers, list_customers_with_open_tickets, update_customer, create_ticket, get_customer_history
- support: draft_response
Rules:
- If the query asks for active customers with open tickets, use list_customers_with_open_tickets(status="active").
- For refund/charged twice/urgent language, mark urgency="high" and route to support.
- If an action needs a customer_id but none is provided, ask SupportAgent to request the missing identifier instead of inventing one.
"""
        if data_agent and support_agent:
            self.data_agent = data_agent
            self.support_agent = support_agent
        else:
            if mcp_server is None:
                raise ValueError("mcp_server is required when no agents are provided")
            self.data_agent = CustomerDataAgent(mcp_server, self.log)
            self.support_agent = SupportAgent(self.data_agent, self.log)
        self.llm_planning_allowlist: Dict[str, Dict[str, Any]] = {
            "customer_data": {
                "get_customer": {"args": {"customer_id": "int"}},
                "list_customers": {"args": {"status": "str|None", "limit": "int"}},
                "list_customers_with_open_tickets": {"args": {"status": "str"}},
                "update_customer": {"args": {"customer_id": "int", "data": "dict"}},
                "create_ticket": {"args": {"customer_id": "int", "issue": "str", "priority": "str"}},
                "get_customer_history": {"args": {"customer_id": "int"}},
            },
            "support": {
                "draft_response": {
                    "args": {
                        "intent": "str",
                        "tone": "str",
                        "urgency": "str",
                        "customer_id": "int|None",
                        "notes": "str|None",
                    }
                },
            },
        }
        self.last_plan: List[Dict[str, Any]] = []

    async def handle(self, query: str) -> Dict[str, Any]:
        self.log.clear()
        self.last_plan = []
        normalized = query.lower()
        customer_id = self._parse_customer_id(query)

        if "get customer information" in normalized:
            self._set_plan(
                [
                    {"agent": "customer_data", "action": "get_customer", "args": {"customer_id": customer_id}},
                    {
                        "agent": "support",
                        "action": "draft_response",
                        "args": {"intent": "customer_info", "tone": "concise", "urgency": "normal"},
                    },
                ]
            )
            response = await self._simple_customer_info(customer_id)
        elif "upgrade" in normalized:
            self._set_plan(
                [
                    {"agent": "customer_data", "action": "get_customer", "args": {"customer_id": customer_id}},
                    {
                        "agent": "customer_data",
                        "action": "get_customer_history",
                        "args": {"customer_id": customer_id, "optional": True},
                    },
                    {
                        "agent": "support",
                        "action": "draft_response",
                        "args": {"intent": "upgrade", "tone": "helpful", "urgency": "normal"},
                    },
                ]
            )
            response = await self._upgrade(customer_id)
        elif "active customers" in normalized and "open tickets" in normalized:
            self._set_plan(
                [
                    {
                        "agent": "customer_data",
                        "action": "list_customers_with_open_tickets",
                        "args": {"status": "active"},
                    },
                    {
                        "agent": "support",
                        "action": "draft_response",
                        "args": {"intent": "list_open_tickets", "tone": "helpful", "urgency": "normal"},
                    },
                ]
            )
            response = await self._active_with_open_tickets()
        elif "charged twice" in normalized or "refund" in normalized:
            self._set_plan(
                [
                    {
                        "agent": "support",
                        "action": "draft_response",
                        "args": {
                            "intent": "refund",
                            "tone": "calm",
                            "urgency": "high",
                            "customer_id": customer_id,
                            "notes": "billing escalation",
                        },
                    }
                ]
            )
            response = await self._escalation(customer_id)
        elif "update my email" in normalized and "ticket history" in normalized:
            self._set_plan(
                [
                    {
                        "agent": "customer_data",
                        "action": "update_customer",
                        "args": {"customer_id": customer_id, "data": {"email": self._parse_email(query)}},
                    },
                    {
                        "agent": "customer_data",
                        "action": "get_customer_history",
                        "args": {"customer_id": customer_id},
                    },
                    {
                        "agent": "support",
                        "action": "draft_response",
                        "args": {
                            "intent": "multi_intent_update_history",
                            "tone": "helpful",
                            "urgency": "normal",
                            "customer_id": customer_id,
                        },
                    },
                ]
            )
            response = await self._multi_intent_update_email(customer_id, self._parse_email(query))
        else:
            response = await self._fallback(customer_id)

        return {"response": response, "log": self.log.dump(), "plan": self.last_plan}

    async def _simple_customer_info(self, customer_id: Optional[int]) -> str:
        if customer_id is None:
            await self.support_agent.draft_response(
                intent="customer_info",
                tone="concise",
                urgency="normal",
                notes="customer_id required",
            )
            return "Please provide a customer ID so I can pull the account details."

        result = await self.data_agent.fetch_customer(customer_id)
        if result.error or not result.result:
            await self.support_agent.draft_response(
                intent="customer_info",
                tone="concise",
                urgency="normal",
                notes="not found",
                customer=result.result,
            )
            return "Customer not found."

        return await self.support_agent.draft_response(
            intent="customer_info",
            tone="concise",
            urgency="normal",
            customer=result.result,
        )

    async def _upgrade(self, customer_id: Optional[int]) -> str:
        if customer_id is None:
            return await self.support_agent.draft_response(
                intent="upgrade",
                tone="helpful",
                urgency="normal",
                notes="missing customer id",
            )

        info = await self.data_agent.fetch_customer(customer_id)
        history = await self.data_agent.history(customer_id)
        return await self.support_agent.draft_response(
            intent="upgrade",
            tone="helpful",
            urgency="normal",
            customer=info.result,
            data={"history": history.result},
        )

    async def _active_with_open_tickets(self) -> str:
        result = await self.data_agent.list_customers_with_open_tickets(status="active")
        return await self.support_agent.draft_response(
            intent="list_open_tickets",
            tone="helpful",
            urgency="normal",
            data=result.result,
            notes="active customers only",
        )

    async def _escalation(self, customer_id: Optional[int]) -> str:
        customer_details = None
        if customer_id is not None:
            lookup = await self.data_agent.fetch_customer(customer_id)
            customer_details = lookup.result
        return await self.support_agent.draft_response(
            intent="refund",
            tone="calm",
            urgency="high",
            customer=customer_details,
        )

    async def _multi_intent_update_email(
        self, customer_id: Optional[int], new_email: Optional[str]
    ) -> str:
        if customer_id is None:
            return await self.support_agent.draft_response(
                intent="multi_intent_update_history",
                tone="helpful",
                urgency="normal",
                notes="missing customer id",
            )

        update_task = None
        if new_email:
            update_task = asyncio.create_task(
                self.data_agent.update_customer(customer_id, {"email": new_email})
            )
        history_task = asyncio.create_task(self.data_agent.history(customer_id))

        updated = await update_task if update_task else None
        history = await history_task
        return await self.support_agent.draft_response(
            intent="multi_intent_update_history",
            tone="helpful",
            urgency="normal",
            customer={"id": customer_id},
            data={"updated": updated.result if updated else None, "history": history.result},
            notes="completed" if updated else "history only",
        )

    async def _fallback(self, customer_id: Optional[int]) -> str:
        customer = None
        if customer_id is not None:
            info = await self.data_agent.fetch_customer(customer_id)
            customer = info.result
        return await self.support_agent.draft_response(
            intent="general",
            tone="helpful",
            urgency="normal",
            customer=customer,
            notes="fallback",
        )

    def _parse_customer_id(self, query: str) -> Optional[int]:
        match = re.search(r"(?:id|customer)\s*(\d+)", query.lower())
        return int(match.group(1)) if match else None

    def _parse_email(self, query: str) -> Optional[str]:
        match = re.search(r"[\w\.\-]+@[\w\-]+\.[\w\-]+", query)
        return match.group(0) if match else None

    def _set_plan(self, steps: List[Dict[str, Any]]) -> None:
        self.last_plan = steps
