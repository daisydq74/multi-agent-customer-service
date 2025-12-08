from __future__ import annotations

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
        if not has_api_key():
            raise RuntimeError("Missing OPENAI_API_KEY (LLM routing is required).")
        self.log = log or ConversationLog()
        if data_agent and support_agent:
            self.data_agent = data_agent
            self.support_agent = support_agent
        else:
            if mcp_server is None:
                raise ValueError("mcp_server is required when no agents are provided")
            self.data_agent = CustomerDataAgent(mcp_server, self.log)
            self.support_agent = SupportAgent(self.data_agent, self.log)
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

    async def handle(self, query: str) -> Dict[str, Any]:
        self.log.clear()
        self.llm.last_used = False
        customer_id = self._parse_customer_id(query)

        plan_payload: Optional[Dict[str, Any]] = self._plan_with_llm(query, customer_id)
        try:
            if plan_payload:
                llm_response = await self._execute_plan(plan_payload, query, customer_id)
            else:
                llm_response = (
                    "I couldn't plan the next steps. Please rephrase your request or include "
                    "any missing details such as your customer id."
                )
        except Exception:
            llm_response = (
                "I couldn't complete your request. Please rephrase it or include required "
                "details (e.g., 'customer 12345')."
            )
        return {
            "response": llm_response,
            "log": self.log.dump(),
            "plan": plan_payload,
            "meta": self.llm_meta(self.llm.last_used),
        }

    def _plan_with_llm(self, query: str, customer_id: Optional[int]) -> Optional[Dict[str, Any]]:
        system_prompt = (
            "You are a routing coordinator. Plan steps across a customer data agent and support agent. "
            "If the customer_id is missing, either request it explicitly in the support draft_response "
            "or return an empty plan with notes describing the missing information. "
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
                "If customer_id is missing and required, ask the user to provide it in the support reply (e.g., 'Please include your customer id').",
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
        self, plan_payload: Dict[str, Any], query: str, customer_id: Optional[int]
    ) -> str:
        data_results: Dict[str, Any] = {}
        last_data_result: Optional[Any] = None
        for step in plan_payload.get("plan", []):
            if step.get("agent") == "customer_data":
                result = await self._run_customer_data_action(
                    step.get("action", ""), step.get("args", {}), customer_id
                )
                if getattr(result, "error", None):
                    raise RuntimeError(f"Data tool error: {result.error}")
                data_results[step.get("action", "")] = result.result
                last_data_result = result.result
            else:
                return await self._run_support_action(plan_payload, step.get("args", {}), query, data_results)

        if plan_payload.get("final_agent") == "support":
            return await self._run_support_action(plan_payload, {}, query, data_results)
        if last_data_result is not None:
            return str(last_data_result)
        return (
            "I couldn't execute the requested steps. Please rephrase your request or include "
            "any missing details."
        )

    async def _run_customer_data_action(
        self, action: str, args: Dict[str, Any], customer_id: Optional[int]
    ):
        if action == "get_customer":
            cid = self._require_customer_id(args.get("customer_id"), customer_id)
            return await self.data_agent.fetch_customer(cid)
        if action == "list_customers":
            return await self.data_agent.list_customers(
                args.get("status"), int(args.get("limit", 10)), sender="Router"
            )
        if action == "update_customer":
            cid = self._require_customer_id(args.get("customer_id"), customer_id)
            data = args.get("data", {}) if isinstance(args.get("data"), dict) else {}
            return await self.data_agent.update_customer(cid, data)
        if action == "create_ticket":
            cid = self._require_customer_id(args.get("customer_id"), customer_id)
            return await self.data_agent.create_ticket(
                cid, args.get("issue", ""), args.get("priority", "medium")
            )
        cid = self._require_customer_id(args.get("customer_id"), customer_id)
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

    def _require_customer_id(self, provided: Any, parsed: Optional[int]) -> int:
        if provided is None and parsed is None:
            raise ValueError(
                "Please include your customer id (e.g., 'customer 12345') so I can look up your account."
            )
        try:
            return int(provided if provided is not None else parsed)
        except (TypeError, ValueError):
            raise ValueError(
                "Please include your customer id (e.g., 'customer 12345') so I can look up your account."
            )

    def llm_meta(self, used_llm: bool) -> Dict[str, Any]:
        if used_llm:
            return {
                "used_llm": True,
                "model": self.router_model,
                "temperature": self.router_temperature,
            }
        return {"used_llm": False, "model": "none", "temperature": "none"}
