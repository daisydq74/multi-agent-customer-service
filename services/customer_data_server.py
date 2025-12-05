from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from mcp_server.ensure_seed_data import ensure_required_records
from mcp_server.server import DB_PATH, MCPServer, ToolResult
from src.agents.base import ConversationLog
from src.agents.customer_data_agent import CustomerDataAgent

app = FastAPI(title="Customer Data Agent Service")

AGENT_CARD: Dict[str, Any] = {
    "id": "customer-data-agent",
    "name": "Customer Data Agent",
    "description": "Provides customer retrieval, updates, and ticket actions via MCP tools.",
    "version": "1.0",
    "rpc": {"url": "http://localhost:8011/rpc"},
    "methods": ["message/send"],
}

mcp_server = MCPServer()
ensure_required_records(DB_PATH)
conversation_log = ConversationLog()
data_agent = CustomerDataAgent(mcp_server, conversation_log)


def _serialize_tool_result(result: ToolResult) -> Dict[str, Any]:
    return {"result": result.result, "error": result.error}


async def _handle_command(command: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if command == "fetch_customer":
        return _serialize_tool_result(
            await data_agent.fetch_customer(int(args.get("customer_id", 0)), sender=args.get("sender", "Router"))
        )
    if command == "list_customers":
        return _serialize_tool_result(
            await data_agent.list_customers(
                args.get("status"), int(args.get("limit", 10)), sender=args.get("sender", "Router")
            )
        )
    if command == "update_customer":
        return _serialize_tool_result(
            await data_agent.update_customer(
                int(args.get("customer_id", 0)), args.get("data", {}), sender=args.get("sender", "Router")
            )
        )
    if command == "create_ticket":
        return _serialize_tool_result(
            await data_agent.create_ticket(
                int(args.get("customer_id", 0)),
                args.get("issue", ""),
                args.get("priority", "medium"),
                sender=args.get("sender", "Router"),
            )
        )
    if command == "history":
        return _serialize_tool_result(
            await data_agent.history(int(args.get("customer_id", 0)), sender=args.get("sender", "Router"))
        )
    if command == "high_priority_tickets":
        tickets = await data_agent.high_priority_tickets(args.get("customer_ids", []))
        return {"result": tickets, "error": None}
    raise ValueError(f"Unknown command: {command}")


async def _handle_message(message: Any) -> Dict[str, Any]:
    conversation_log.clear()
    if isinstance(message, dict):
        command = message.get("command")
        args = message.get("args", {})
        return await _handle_command(command, args)
    return {"result": f"CustomerDataAgent received: {message}", "error": None}


@app.get("/.well-known/agent-card.json")
async def agent_card() -> Dict[str, Any]:
    return AGENT_CARD


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
        payload = await _handle_message(message)
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"message": payload}})
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}},
            status_code=500,
        )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8011)
