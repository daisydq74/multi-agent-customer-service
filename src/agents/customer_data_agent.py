import asyncio
from typing import Any, Dict, List, Optional

from mcp_server.server import MCPServer, ToolResult
from src.agents.base import ConversationLog


class CustomerDataAgent:
    """Specialist agent wrapping MCP data tools."""

    def __init__(self, mcp_server: MCPServer, log: ConversationLog) -> None:
        self.server = mcp_server
        self.log = log
        self.name = "CustomerData"
        self.llm_tool_allowlist: Dict[str, Dict[str, Any]] = {
            "get_customer": {"args": {"customer_id": "int"}},
            "list_customers": {"args": {"status": "str|None", "limit": "int"}},
            "list_customers_with_open_tickets": {"args": {"status": "str"}},
            "update_customer": {"args": {"customer_id": "int", "data": "dict"}},
            "create_ticket": {"args": {"customer_id": "int", "issue": "str", "priority": "str"}},
            "get_customer_history": {"args": {"customer_id": "int"}},
        }

    async def fetch_customer(self, customer_id: int, sender: str = "Router") -> ToolResult:
        self.log.record(sender, self.name, "get_customer", {"customer_id": customer_id})
        return await asyncio.to_thread(self.server.get_customer, customer_id)

    async def get_customer(self, customer_id: int, sender: str = "Router") -> ToolResult:
        return await self.fetch_customer(customer_id, sender=sender)

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

    async def list_customers_with_open_tickets(
        self, status: str = "active", sender: str = "Router"
    ) -> ToolResult:
        self.log.record(
            sender,
            self.name,
            "list_customers_with_open_tickets",
            {"status": status},
        )
        return await asyncio.to_thread(self.server.list_customers_with_open_tickets, status)
