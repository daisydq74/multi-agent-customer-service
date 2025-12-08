from __future__ import annotations
import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple

from mcp_server.server import MCPServer, ToolResult
from src.agents.base import ConversationLog
from src.llm.openai_chat_llm import OpenAIChatLLM, has_api_key, safe_json_loads


ALLOWED_TOOLS: Dict[str, Dict[str, List[str]]] = {
    "get_customer": {"required": ["customer_id"]},
    "list_customers": {"required": []},
    "update_customer": {"required": ["customer_id", "data"]},
    "create_ticket": {"required": ["customer_id", "issue"]},
    "get_customer_history": {"required": ["customer_id"]},
}


class CustomerDataAgent:
    """Specialist agent wrapping MCP data tools."""

    def __init__(self, mcp_server: MCPServer, log: ConversationLog) -> None:
        if not has_api_key():
            raise RuntimeError("Missing OPENAI_API_KEY (LLM routing is required).")
        self.server = mcp_server
        self.log = log
        self.name = "CustomerData"
        self.temperature = float(os.getenv("OPENAI_TEMPERATURE_DATA") or 0)
        self.max_tokens = int(os.getenv("OPENAI_MAX_TOKENS_DATA") or 250)
        model = os.getenv("OPENAI_MODEL_DATA", "gpt-4o-mini")
        self.model = model
        self.llm = OpenAIChatLLM(
            model_env_var="OPENAI_MODEL_DATA", default_model=model, model=model
        )

    async def fetch_customer(self, customer_id: int, sender: str = "Router") -> ToolResult:
        self.log.record(sender, self.name, "get_customer", {"customer_id": customer_id})
        return await asyncio.to_thread(self.server.get_customer, customer_id)

    async def list_customers(
        self, status: Optional[str] = None, limit: int = 10, sender: str = "Router"
    ) -> ToolResult:
        self.log.record(sender, self.name, "list_customers", {"status": status, "limit": limit})
        return await asyncio.to_thread(self.server.list_customers, status, limit)

    async def update_customer(
        self, customer_id: int, data: Dict[str, Any], sender: str = "Router"
    ) -> ToolResult:
        self.log.record(sender, self.name, "update_customer", {"customer_id": customer_id, "data": data})
        return await asyncio.to_thread(self.server.update_customer, customer_id, data)

    async def create_ticket(
        self, customer_id: int, issue: str, priority: str = "medium", sender: str = "Router"
    ) -> ToolResult:
        self.log.record(
            sender,
            self.name,
            "create_ticket",
            {"customer_id": customer_id, "issue": issue, "priority": priority},
        )
        return await asyncio.to_thread(self.server.create_ticket, customer_id, issue, priority)

    async def history(self, customer_id: int, sender: str = "Router") -> ToolResult:
        self.log.record(sender, self.name, "get_customer_history", {"customer_id": customer_id})
        return await asyncio.to_thread(self.server.get_customer_history, customer_id)

    async def high_priority_tickets(self, customer_ids: List[int]) -> List[Dict[str, Any]]:
        tickets: List[Dict[str, Any]] = []
        for cid in customer_ids:
            history = await self.history(cid)
            if history.result:
                tickets.extend([t for t in history.result if t.get("priority") == "high"])
        return tickets

    async def handle_query(self, query: str, sender: str = "Router") -> Dict[str, Any]:
        """LLM-backed tool selection with strict validation and no keyword fallback."""
        self.llm.last_used = False

        system_prompt = (
            "You decide which MCP tool to call for a customer support backend."
            " Allowed tools: get_customer, list_customers, update_customer, create_ticket, get_customer_history."
            " Return a JSON object only with fields 'tool' and 'args'."
        )
        user_prompt = (
            "User request: "
            + query
            + "\nReturn JSON. Do not include markdown or commentary."
        )

        try:
            reply = await asyncio.to_thread(
                self.llm.generate,
                system_prompt,
                user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            payload = safe_json_loads(reply)
            validated = self._validate_tool_payload(payload)
            if not validated:
                raise ValueError("Invalid tool selection")
            tool, args = validated
            response = await self._execute_tool(tool, args, sender)
            response["meta"] = self.llm_meta(self.llm.last_used)
            return response
        except Exception:
            return {
                "tool": None,
                "args": {},
                "result": None,
                "error": "Unable to process request. Please rephrase with the required details, including your customer id if needed.",
                "meta": self.llm_meta(self.llm.last_used),
            }

    async def _execute_tool(self, tool: str, args: Dict[str, Any], sender: str) -> Dict[str, Any]:
        result: ToolResult
        if tool == "get_customer":
            result = await self.fetch_customer(int(args["customer_id"]), sender=sender)
        elif tool == "list_customers":
            result = await self.list_customers(
                args.get("status"), int(args.get("limit", 10)), sender=sender
            )
        elif tool == "update_customer":
            result = await self.update_customer(
                int(args["customer_id"]), args.get("data", {}), sender=sender
            )
        elif tool == "create_ticket":
            result = await self.create_ticket(
                int(args["customer_id"]),
                args.get("issue", ""),
                args.get("priority", "medium"),
                sender=sender,
            )
        else:  # get_customer_history
            result = await self.history(int(args["customer_id"]), sender=sender)

        response: Dict[str, Any] = {
            "tool": tool,
            "args": args,
            "result": result.result,
            "error": result.error,
        }
        return response

    def llm_meta(self, used_llm: bool) -> Dict[str, Any]:
        if used_llm:
            return {
                "used_llm": True,
                "model": self.model,
                "temperature": self.temperature,
            }
        return {"used_llm": False, "model": "none", "temperature": "none"}

    def _validate_tool_payload(self, payload: Any) -> Optional[Tuple[str, Dict[str, Any]]]:
        if not isinstance(payload, dict):
            return None
        tool = payload.get("tool")
        args = payload.get("args")
        if tool not in ALLOWED_TOOLS or not isinstance(args, dict):
            return None
        required = ALLOWED_TOOLS[tool]["required"]
        for key in required:
            if key not in args:
                return None
        if tool in {"get_customer", "get_customer_history", "update_customer", "create_ticket"}:
            if not self._is_int(args.get("customer_id")):
                return None
            args["customer_id"] = int(args["customer_id"])
        if tool == "update_customer" and not isinstance(args.get("data"), dict):
            return None
        if tool == "create_ticket":
            if not isinstance(args.get("issue"), str):
                return None
            if "priority" in args and not isinstance(args.get("priority"), str):
                return None
        if tool == "list_customers" and args and not isinstance(args, dict):
            return None
        return tool, args

    def _is_int(self, value: Any) -> bool:
        try:
            int(value)
            return True
        except (TypeError, ValueError):
            return False
