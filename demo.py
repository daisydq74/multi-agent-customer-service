from __future__ import annotations

import asyncio
from pathlib import Path

from mcp_server.ensure_seed_data import ensure_required_records
from mcp_server.server import DB_PATH, MCPServer, reset_database
from src.agents.router_agent import RouterAgent


async def run_scenarios() -> None:
    server = MCPServer()
    router = RouterAgent(server)

    scenarios = [
        "Get customer information for ID 5",
        "I want to cancel my subscription but I'm having billing issues",
        "Show me all active customers who have open tickets",
        "I've been charged twice, please refund immediately!",
        "Update my email to new@email.com\n and show my ticket history",
        "What's the status of all high-priority tickets for premium customers?",
    ]

    transcript_lines = []
    transcript_path = Path("demos/output/run.log")
    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    for idx, query in enumerate(scenarios, start=1):
        print(f"\n=== Scenario {idx} ===")
        print(f"Query: {query}")
        result = await router.handle(query)
        print("A2A Log:")
        print(result["log"])
        print("Answer:", result["response"])

        transcript_lines.append(f"=== Scenario {idx} ===")
        transcript_lines.append(f"Query: {query}")
        transcript_lines.append("A2A Log:")
        transcript_lines.append(result["log"])
        transcript_lines.append(f"Answer: {result['response']}")
        transcript_lines.append("")

    transcript_path.write_text("\n".join(transcript_lines), encoding="utf-8")


if __name__ == "__main__":
    reset_database()
    ensure_required_records(DB_PATH)
    asyncio.run(run_scenarios())
