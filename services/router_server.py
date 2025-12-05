from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.a2a.client import A2ASimpleClient
from src.agents.base import ConversationLog
from src.agents.router_agent import RouterAgent

app = FastAPI(title="Router Agent Service")

ROUTER_CARD: Dict[str, Any] = {
    "id": "router-agent",
    "name": "Router Agent",
    "description": "Primary entry point; routes requests to customer-data and support agents via A2A.",
    "version": "1.0",
    "rpc": {"url": "http://localhost:8010/rpc"},
    "methods": ["message/send"],
}

DATA_AGENT_URL = os.environ.get("DATA_AGENT_URL", "http://localhost:8011")
SUPPORT_AGENT_URL = os.environ.get("SUPPORT_AGENT_URL", "http://localhost:8012")

data_agent_client = A2ASimpleClient(DATA_AGENT_URL)
support_agent_client = A2ASimpleClient(SUPPORT_AGENT_URL)

conversation_log = ConversationLog()


class RemoteToolResult(SimpleNamespace):
    result: Any
    error: Optional[str]


class CustomerDataProxy:
    def __init__(self, client: A2ASimpleClient) -> None:
        self.client = client

    async def fetch_customer(self, customer_id: int, sender: str = "Router") -> RemoteToolResult:
        payload = await self.client.send_message(
            {"command": "fetch_customer", "args": {"customer_id": customer_id, "sender": sender}}
        )
        return RemoteToolResult(result=payload.get("result"), error=payload.get("error"))

    async def list_customers(self, status: Optional[str] = None, limit: int = 10, sender: str = "Router") -> RemoteToolResult:
        payload = await self.client.send_message(
            {
                "command": "list_customers",
                "args": {"status": status, "limit": limit, "sender": sender},
            }
        )
        return RemoteToolResult(result=payload.get("result"), error=payload.get("error"))

    async def update_customer(self, customer_id: int, data: Dict[str, Any], sender: str = "Router") -> RemoteToolResult:
        payload = await self.client.send_message(
            {
                "command": "update_customer",
                "args": {"customer_id": customer_id, "data": data, "sender": sender},
            }
        )
        return RemoteToolResult(result=payload.get("result"), error=payload.get("error"))

    async def create_ticket(
        self, customer_id: int, issue: str, priority: str = "medium", sender: str = "Router"
    ) -> RemoteToolResult:
        payload = await self.client.send_message(
            {
                "command": "create_ticket",
                "args": {
                    "customer_id": customer_id,
                    "issue": issue,
                    "priority": priority,
                    "sender": sender,
                },
            }
        )
        return RemoteToolResult(result=payload.get("result"), error=payload.get("error"))

    async def history(self, customer_id: int, sender: str = "Router") -> RemoteToolResult:
        payload = await self.client.send_message(
            {"command": "history", "args": {"customer_id": customer_id, "sender": sender}}
        )
        return RemoteToolResult(result=payload.get("result"), error=payload.get("error"))

    async def high_priority_tickets(self, customer_ids: list[int]) -> list[Dict[str, Any]]:
        payload = await self.client.send_message(
            {"command": "high_priority_tickets", "args": {"customer_ids": customer_ids}}
        )
        return payload.get("result", [])


class SupportProxy:
    def __init__(self, client: A2ASimpleClient) -> None:
        self.client = client

    async def handle_support(
        self,
        customer: Optional[Dict[str, Any]],
        issue: str,
        urgent: bool = False,
        needs_context: bool = False,
    ) -> str:
        payload = await self.client.send_message(
            {
                "command": "handle_support",
                "args": {
                    "customer": customer,
                    "issue": issue,
                    "urgent": urgent,
                    "needs_context": needs_context,
                },
            }
        )
        return payload.get("result", "")

    async def ensure_ticket(self, customer_id: int, issue: str, priority: str = "medium") -> Dict[str, Any]:
        payload = await self.client.send_message(
            {
                "command": "ensure_ticket",
                "args": {"customer_id": customer_id, "issue": issue, "priority": priority},
            }
        )
        return payload.get("result", {})

    async def summarize_history(self, customer_id: int) -> str:
        payload = await self.client.send_message(
            {"command": "summarize_history", "args": {"customer_id": customer_id}}
        )
        return payload.get("result", "")


router_agent = RouterAgent(
    None,
    log=conversation_log,
    data_agent=CustomerDataProxy(data_agent_client),
    support_agent=SupportProxy(support_agent_client),
)


@app.get("/.well-known/agent-card.json")
async def agent_card() -> Dict[str, Any]:
    return ROUTER_CARD


@app.post("/rpc")
async def rpc_endpoint(request: Dict[str, Any]):
    req_id = request.get("id")
    if request.get("method") != "message/send":
        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Unsupported method"}},
            status_code=400,
        )

    message = request.get("params", {}).get("message")
    try:
        result = await router_agent.handle(str(message))
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"message": result}})
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}},
            status_code=500,
        )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
