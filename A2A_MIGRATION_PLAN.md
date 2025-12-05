# Task: Minimal-change migration to A2A specs (quickstart-like)

Goal: Keep existing agents under src/agents/ (router_agent.py, customer_data_agent.py, support_agent.py) mostly unchanged, but wrap them as A2A-spec services with Agent Card + JSON-RPC message/send, similar to a2a_quickstart.py.

## Required end state
1) Three runnable HTTP services (FastAPI/Starlette):
   - services/router_server.py  (port 8010)
   - services/customer_data_server.py (port 8011)
   - services/support_server.py (port 8012)

2) Each service exposes:
   - GET /.well-known/agent-card.json   (Agent Card)
   - POST /rpc                          (JSON-RPC 2.0)
     Supports method: "message/send"
     Request contains a text message; response returns text.

3) RouterAgent MUST call other agents via A2A client over HTTP (NOT by importing and calling agent objects directly).
   - Use official a2a-sdk style: fetch agent card from /.well-known/agent-card.json then send JSON-RPC message/send.
   - Add src/a2a/client.py implementing A2ASimpleClient (based on a2a_quickstart.py).

4) CustomerDataAgent continues to use the existing MCPServer tools:
   - get_customer(customer_id)
   - list_customers(status, limit)
   - update_customer(customer_id, data)
   - create_ticket(customer_id, issue, priority)
   - get_customer_history(customer_id)

5) Add end-to-end demo script:
   - demos/run_a2a_spec_demo.py
   - Starts 3 services (subprocess) and runs >=3 scenarios:
     a) "Get customer information for ID 5"
     b) "I want to cancel my subscription but I'm having billing issues"
     c) "What's the status of all high-priority tickets for premium customers?"
   - Writes transcript to demos/output/run_a2a_spec.log and prints to stdout.

6) Update README.md with:
   - venv instructions
   - requirements.txt
   - how to start each service
   - how to run the demo

7) Update requirements.txt (or create if missing) including:
   - fastapi, uvicorn, httpx, a2a-sdk (pin versions if needed)

## Acceptance tests (must pass)
- Run 3 services:
  python -m uvicorn services.customer_data_server:app --port 8011
  python -m uvicorn services.support_server:app --port 8012
  python -m uvicorn services.router_server:app --port 8010
- Run demo:
  python demos/run_a2a_spec_demo.py
- Demo output shows A2A hops and uses Agent Card discovery (calls /.well-known/agent-card.json) and JSON-RPC message/send.

## Constraints
- Minimal edits to src/agents/*; prefer wrapper servers and a client layer.
- Keep existing demo/run.log working if possible, but new A2A demo is mandatory.
