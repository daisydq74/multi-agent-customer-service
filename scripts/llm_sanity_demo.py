"""Simple sanity demo that mirrors the LLM planning flow for common queries."""

import asyncio
import json
from pathlib import Path
from typing import List

from mcp_server.ensure_seed_data import ensure_required_records
from mcp_server.server import DB_PATH, MCPServer, reset_database
from src.agents.router_agent import RouterAgent

SCENARIOS: List[str] = [
    "Get customer information for ID 5",
    "I'm customer 12345 and need help upgrading my account",
    "Show me all active customers who have open tickets",
    "I've been charged twice, please refund immediately!",
    "Update my email to new@email.com and show my ticket history",
]


async def run_demo() -> None:
    reset_database()
    ensure_required_records(DB_PATH)

    server = MCPServer()
    router = RouterAgent(server)

    transcript_path = Path("demos/output/llm_sanity_demo.log")
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_lines: List[str] = []

    for query in SCENARIOS:
        print(f"\n=== Query: {query} ===")
        result = await router.handle(query)
        print("Router plan:")
        print(json.dumps(result["plan"], indent=2))
        print("A2A Log:")
        print(result["log"])
        print("Answer:", result["response"])

        transcript_lines.append(f"Query: {query}")
        transcript_lines.append("Plan:")
        transcript_lines.append(json.dumps(result["plan"], indent=2))
        transcript_lines.append("A2A Log:")
        transcript_lines.append(result["log"])
        transcript_lines.append(f"Answer: {result['response']}")
        transcript_lines.append("")

    transcript_path.write_text("\n".join(transcript_lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(run_demo())
