from __future__ import annotations

from typing import Any, Dict, List, Optional

from mcp_server.server import MCPServer, ToolResult
from src.agents.base import ConversationLog


class CustomerDataAgent:
    """Specialist agent that wraps MCP tools."""

    def __init__(self, mcp_server: MCPServer, log: ConversationLog) -> None:
        self.server = mcp_server
        self.log = log
        self.name = "customer-data-agent"

    def fetch_customer(self, customer_id: int) -> ToolResult:
        self.log.record(
            "router",
            self.name,
            "get_customer",
            {"customer_id": customer_id},
        )
        return self.server.get_customer(customer_id)

    def list_customers(self, status: str | None = None, limit: int = 20) -> ToolResult:
        self.log.record(
            "router",
            self.name,
            "list_customers",
            {"status": status, "limit": limit},
        )
        return self.server.list_customers(status=status, limit=limit)

    def update_customer(self, customer_id: int, data: Dict[str, Any]) -> ToolResult:
        self.log.record(
            "router",
            self.name,
            "update_customer",
            {"customer_id": customer_id, "data": data},
        )
        result = self.server.update_customer(customer_id, data)
        self.log.record(
            self.name,
            "router",
            "update_customer.result",
            {"customer_id": customer_id, "result": result.result},
        )
        return result

    def history(self, customer_id: int) -> ToolResult:
        self.log.record(
            "router",
            self.name,
            "get_customer_history",
            {"customer_id": customer_id},
        )
        return self.server.get_customer_history(customer_id)

    def high_priority_tickets_for_customers(self, customer_ids: List[int]) -> List[Dict[str, Any]]:
        tickets: List[Dict[str, Any]] = []
        for cid in customer_ids:
            history = self.history(cid)
            if history.result:
                tickets.extend(
                    [t for t in history.result if t.get("priority") == "high"]
                )
        return tickets
