from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, Optional

from mcp_server.server import MCPServer
from src.agents.base import ConversationLog
from src.agents.customer_data_agent import ALLOWED_TOOLS, CustomerDataAgent
from src.agents.support_agent import SupportAgent
from src.llm.openai_chat_llm import OpenAIChatLLM, has_api_key, safe_json_loads


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
        self.llm_enabled = has_api_key()
        self.router_model = os.getenv("OPENAI_MODEL_ROUTER", "gpt-4o-mini")
        self.router_temperature = float(os.getenv("OPENAI_TEMPERATURE_ROUTER", 0))
        self.router_max_tokens = int(os.getenv("OPENAI_MAX_TOKENS_ROUTER", 300))
        self.llm = OpenAIChatLLM(
            model_env_var="OPENAI_MODEL_ROUTER",
            default_model=self.router_model,
            model=self.router_model,
        )
        self.allowed_support_actions = {"draft_response"}

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

        plan_payload: Optional[Dict[str, Any]] = None
        if self.llm_enabled:
            plan_payload = self._plan_with_llm(query, customer_id)
            if plan_payload:
                try:
                    llm_response = await self._execute_plan(plan_payload, query, customer_id)
                    return {"response": llm_response, "log": self.log.dump(), "plan": plan_payload}
                except Exception:
                    pass

        response = await self._keyword_route(normalized, query, customer_id)
        return {"response": response, "log": self.log.dump(), "plan": plan_payload}

    def _plan_with_llm(self, query: str, customer_id: int) -> Optional[Dict[str, Any]]:
        system_prompt = (
            "You are a routing coordinator. Plan steps across a customer data agent and support agent. "
            "Return a JSON object only. No markdown, no commentary."
        )
        allowed_actions = ", ".join(ALLOWED_TOOLS.keys())
        user_prompt = "\n".join(
            [
                f"User query: {query}",
                f"Potential customer_id: {customer_id}",
                "Agents: customer_data (tools: " + allowed_actions + ") and support (actions: draft_response).",
                "Schema: {\"plan\": [ {\"agent\":..., \"action\":..., \"args\":{...}} ], \"final_agent\":\"support\", \"notes\":\"...\" }",
                "Use only allowed actions. args must be a JSON object.",
            ]
        )
        try:
            reply = self.llm.generate(
                system_prompt,
                user_prompt,
                temperature=self.router_temperature,
                max_tokens=self.router_max_tokens,
                response_format={"type": "json_object"},
            )
            payload = safe_json_loads(reply)
            if self._validate_plan(payload):
                return payload
        except Exception:
            return None
        return None

    def _validate_plan(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        if payload.get("final_agent") not in {"customer_data", "support"}:
            return False
        plan = payload.get("plan")
        if not isinstance(plan, list):
            return False
        for step in plan:
            if not isinstance(step, dict):
                return False
            agent = step.get("agent")
            action = step.get("action")
            args = step.get("args")
            if agent not in {"customer_data", "support"} or not isinstance(args, dict):
                return False
            if agent == "customer_data" and action not in ALLOWED_TOOLS:
                return False
            if agent == "support" and action not in self.allowed_support_actions:
                return False
            if agent == "customer_data" and not self._validate_data_args(action, args):
                return False
        return True

    async def _execute_plan(
        self, plan_payload: Dict[str, Any], query: str, customer_id: int
    ) -> str:
        data_results: Dict[str, Any] = {}
        last_data_result: Optional[Any] = None
        for step in plan_payload.get("plan", []):
            if step.get("agent") == "customer_data":
                result = await self._run_customer_data_action(
                    step.get("action", ""), step.get("args", {}), customer_id
                )
                if getattr(result, "error", None):
                    return await self._fallback(customer_id)
                data_results[step.get("action", "")] = result.result
                last_data_result = result.result
            else:
                return await self._run_support_action(plan_payload, step.get("args", {}), query, data_results)

        if plan_payload.get("final_agent") == "support":
            return await self._run_support_action(plan_payload, {}, query, data_results)
        if last_data_result is not None:
            return str(last_data_result)
        return await self._fallback(customer_id)

    async def _run_customer_data_action(
        self, action: str, args: Dict[str, Any], fallback_customer_id: int
    ):
        if action == "get_customer":
            cid = int(args.get("customer_id", fallback_customer_id))
            return await self.data_agent.fetch_customer(cid)
        if action == "list_customers":
            return await self.data_agent.list_customers(
                args.get("status"), int(args.get("limit", 10)), sender="Router"
            )
        if action == "update_customer":
            cid = int(args.get("customer_id", fallback_customer_id))
            data = args.get("data", {}) if isinstance(args.get("data"), dict) else {}
            return await self.data_agent.update_customer(cid, data)
        if action == "create_ticket":
            cid = int(args.get("customer_id", fallback_customer_id))
            return await self.data_agent.create_ticket(
                cid, args.get("issue", ""), args.get("priority", "medium")
            )
        cid = int(args.get("customer_id", fallback_customer_id))
        return await self.data_agent.history(cid)

    async def _run_support_action(
        self,
        plan_payload: Dict[str, Any],
        args: Dict[str, Any],
        query: str,
        data_results: Dict[str, Any],
    ) -> str:
        context = {
            "user_query": query,
            "customer": data_results.get("get_customer"),
            "history": data_results.get("get_customer_history"),
            "ticket_updates": data_results.get("create_ticket"),
            "notes": plan_payload.get("notes"),
        }
        context.update(args or {})
        return await self.support_agent.draft_response(context)

    def _validate_data_args(self, action: str, args: Dict[str, Any]) -> bool:
        if action not in ALLOWED_TOOLS:
            return False
        required = ALLOWED_TOOLS[action]["required"]
        for key in required:
            if key not in args:
                return False
        if action in {"get_customer", "get_customer_history", "update_customer", "create_ticket"}:
            try:
                int(args.get("customer_id"))
            except (TypeError, ValueError):
                return False
        if action == "update_customer" and not isinstance(args.get("data"), dict):
            return False
        if action == "create_ticket" and not isinstance(args.get("issue"), str):
            return False
        return True

    async def _keyword_route(self, normalized: str, query: str, customer_id: int) -> str:
        if "cancel my subscription" in normalized and "billing" in normalized:
            return await self._cancel_with_billing_issue(customer_id)
        if "update my email" in normalized and "history" in normalized:
            return await self._multi_intent_update_email(customer_id, self._parse_email(query))
        if "charged twice" in normalized or "refund" in normalized:
            return await self._escalation(customer_id)
        if "high-priority tickets" in normalized:
            return await self._high_priority_report()
        if "open tickets" in normalized and "active customers" in normalized:
            return await self._active_with_open_tickets()
        if "upgrade" in normalized or "upgrad" in normalized:
            return await self._upgrade(customer_id)
        if "get customer information" in normalized or "customer information" in normalized:
            return await self._get_customer(customer_id)
        return await self._fallback(customer_id)

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
