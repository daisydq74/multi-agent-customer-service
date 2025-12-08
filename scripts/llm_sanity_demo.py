from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from pprint import pprint

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.ensure_seed_data import ensure_required_records
from mcp_server.server import DB_PATH, MCPServer, reset_database
from src.agents.router_agent import RouterAgent


async def main() -> None:
    reset_database()
    ensure_required_records(DB_PATH)

    router = RouterAgent(MCPServer())
    queries = [
        "I want to see details for customer 3",
        "Please create a ticket for customer 2 about a login issue",
        "Show active customers with any open tickets",
    ]

    for query in queries:
        print("\n=== Query ===")
        print(query)
        result = await router.handle(query)
        print("Plan (may be None without OPENAI_API_KEY):")
        pprint(result.get("plan"))
        print("A2A Log:")
        print(result.get("log"))
        print("Response:")
        print(result.get("response"))


if __name__ == "__main__":
    asyncio.run(main())
