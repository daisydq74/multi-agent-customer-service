"""Simple sanity demo that mirrors the LLM planning flow for common queries."""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

from mcp_server.ensure_seed_data import ensure_required_records
from mcp_server.server import DB_PATH, MCPServer, reset_database
from src.agents.router_agent import RouterAgent

SCENARIOS: List[Dict[str, Any]] = [
    {
        "query": "Get customer information for ID 5",
        "plan": [
            {"agent": "customer_data", "action": "get_customer", "args": {"customer_id": 5}},
            {"agent": "support", "action": "handle_support", "args": {"issue": "General inquiry"}},
        ],
    },
    {
        "query": "Update my email to demo@example.com and show my ticket history",
        "plan": [
            {
                "agent": "customer_data",
                "action": "update_customer",
                "args": {"customer_id": 1, "data": {"email": "demo@example.com"}},
            },
            {"agent": "customer_data", "action": "get_customer_history", "args": {"customer_id": 1}},
            {"agent": "support", "action": "summarize_history", "args": {"customer_id": 1}},
        ],
    },
    {
        "query": "Show active customers with any open tickets",
        "plan": [
            {
                "agent": "customer_data",
                "action": "list_customers_with_open_tickets",
                "args": {"status": "active"},
            },
            {
                "agent": "support",
                "action": "draft_response",
                "args": {"input": "Summarize open tickets per active customer"},
            },
        ],
    },
]


async def _print_plan(plan: List[Dict[str, Any]]) -> None:
    for step in plan:
        print(f"- {step['agent']}.{step['action']} args={json.dumps(step['args'])}")


async def run_demo() -> None:
    reset_database()
    ensure_required_records(DB_PATH)

    server = MCPServer()
    router = RouterAgent(server)

    transcript_path = Path("demos/output/llm_sanity_demo.log")
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_lines: List[str] = []

    for scenario in SCENARIOS:
        query = scenario["query"]
        plan = scenario["plan"]
        print(f"\n=== Query: {query} ===")
        print("Planned actions:")
        await _print_plan(plan)

        if any(step["action"] == "list_customers_with_open_tickets" for step in plan):
            preview = await router.data_agent.list_customers_with_open_tickets(status="active")
            print("Open ticket preview:")
            print(json.dumps(preview.result, indent=2))

        result = await router.handle(query)
        print("A2A Log:")
        print(result["log"])
        print("Answer:", result["response"])

        transcript_lines.append(f"Query: {query}")
        transcript_lines.append("Plan:")
        transcript_lines.extend(
            f"- {step['agent']}.{step['action']} args={json.dumps(step['args'])}" for step in plan
        )
        if any(step["action"] == "list_customers_with_open_tickets" for step in plan):
            transcript_lines.append("Preview:")
            transcript_lines.append(json.dumps(preview.result, indent=2))
        transcript_lines.append("A2A Log:")
        transcript_lines.append(result["log"])
        transcript_lines.append(f"Answer: {result['response']}")
        transcript_lines.append("")

    transcript_path.write_text("\n".join(transcript_lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(run_demo())
