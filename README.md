# Multi-Agent Customer Service (MCP + A2A)

Minimal, runnable reference: FastMCP server over SQLite plus three coordinating agents (router, customer data, support) with explicit agent-to-agent logs.

## Project Layout
- `mcp_server/server.py` — FastMCP server exposing required tools (`get_customer`, `list_customers`, `update_customer`, `create_ticket`, `get_customer_history`) with SQLite backing.
- `src/agents/router_agent.py` — Async orchestrator/Router agent that allocates tasks, negotiates escalation, and coordinates multi-step flows.
- `src/agents/customer_data_agent.py` — Customer Data specialist that wraps MCP tools with A2A logging.
- `src/agents/support_agent.py` — Support specialist handling general support, escalations, and summaries; may request context from the data agent.
- `demo.py` — End-to-end runner that seeds the DB and executes the required scenarios.
- `database_setup.py` — Provided helper (not used by the demo) kept for reference.

## Setup & Run
1. Python 3.11+ recommended.
2. (Optional) Create a virtual environment and activate it.
3. Start the MCP server (HTTP at `http://localhost:8000/mcp`):
   ```bash
   python mcp_server/server.py
   ```
4. To run the multi-agent demo instead:
   ```bash
   python demo.py
   ```
The demo resets `mcp_server/support.db`, seeds sample data, runs the test scenarios, prints the customer-facing response plus the A2A log for each hop, and writes a transcript to `demos/output/run.log`.

## MCP Server Tools
All tools live in `mcp_server/server.py`, exposed via FastMCP over HTTP:
- `get_customer(customer_id)`
- `list_customers(status, limit)`
- `update_customer(customer_id, data)` (validates allowed fields)
- `create_ticket(customer_id, issue, priority)`
- `get_customer_history(customer_id)`

## Agents & Coordination
- Router allocates requests, negotiates escalation, and sequences multi-step work.
- Customer Data Agent calls MCP tools for retrieval/updates.
- Support Agent handles responses, ticket creation, and reporting.
- `ConversationLog` records every Router ↔ Agent hop; `demo.py` prints it so you can trace coordination.

## Demo Scenarios (in order)
`demo.py` runs:
1. `Get customer information for ID 5`
2. `I'm customer 12345 and need help upgrading my account`
3. `Show me all active customers who have open tickets`
4. `I've been charged twice, please refund immediately!`
5. `Update my email to new@email.com` (newline) `and show my ticket history`
6. `What's the status of all high-priority tickets for premium customers?`

Outputs show both the response and the A2A log for traceability.

## Extending
- Adjust seed data in `mcp_server/server.py` if you want different fixtures.
- Replace the simple keyword routing in `src/agents/router_agent.py` with your preferred intent classifier.
- The MCP server class is framework-agnostic; you can wrap it with an HTTP or socket transport if needed.
