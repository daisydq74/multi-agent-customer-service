from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from mcp_server.ensure_seed_data import ensure_required_records
from mcp_server.server import DB_PATH, MCPServer
from src.agents.base import ConversationLog
from src.agents.customer_data_agent import CustomerDataAgent
from src.agents.support_agent import SupportAgent

app = FastAPI(title="Support Agent Service")

AGENT_CARD: Dict[str, Any] = {
    "id": "support-agent",
    "name": "Support Agent",
    "description": "Handles support reasoning, escalations, and ticketing.",
    "version": "1.0",
    "rpc": {"url": "http://localhost:8012/rpc"},
    "methods": ["message/send"],
}

mcp_server = MCPServer()
ensure_required_records(DB_PATH)
conversation_log = ConversationLog()
data_agent = CustomerDataAgent(mcp_server, conversation_log)
support_agent = SupportAgent(data_agent, conversation_log)


async def _handle_command(command: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if command == "handle_support":
        reply = await support_agent.handle_support(
            args.get("customer"),
            args.get("issue", ""),
            urgent=bool(args.get("urgent", False)),
            needs_context=bool(args.get("needs_context", False)),
        )
        return {"result": reply, "error": None}
    if command == "ensure_ticket":
        ticket = await support_agent.ensure_ticket(
            int(args.get("customer_id", 0)), args.get("issue", ""), priority=args.get("priority", "medium")
        )
        return {"result": ticket, "error": None}
    if command == "summarize_history":
        summary = await support_agent.summarize_history(int(args.get("customer_id", 0)))
        return {"result": summary, "error": None}
    raise ValueError(f"Unknown command: {command}")


async def _handle_message(message: Any) -> Dict[str, Any]:
    conversation_log.clear()
    if isinstance(message, dict):
        command = message.get("command")
        args = message.get("args", {})
        return await _handle_command(command, args)
    return {"result": f"SupportAgent received: {message}", "error": None}


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

    uvicorn.run(app, host="0.0.0.0", port=8012)
