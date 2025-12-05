# Requirement → Evidence Map

| Requirement | Implementation | How to Run/Verify |
| --- | --- | --- |
| Router agent orchestrates routing and coordination | `src/agents/router_agent.py` (`RouterAgent`) | `python demo.py` scenarios 1-6 print router-led flows |
| Customer Data agent specializes in MCP data access | `src/agents/customer_data_agent.py` (`CustomerDataAgent`) | `python demo.py` (watch A2A log entries Router→CustomerData) |
| Support agent handles support/escalation | `src/agents/support_agent.py` (`SupportAgent`) | `python demo.py` (log entries Router→Support and Support→CustomerData) |
| A2A logging format `[A2A] from=... to=... action=... args=...` | `src/agents/base.py` (`ConversationLog.format`) | `python demo.py` (observe printed logs and `demos/output/run.log`) |
| Async handling and parallel multi-intent | `src/agents/router_agent.py` (`_multi_intent_update_email` with `asyncio.gather`) | `python demo.py` scenario 5 |
| Demo runs required queries in order and saves transcript | `demo.py`, output file `demos/output/run.log` | `python demo.py` |
| Minimal repo structure (mcp_server/, src/agents/, demo.py, README.md) | repo tree | `Get-ChildItem` in repo root |
| MCP server exposes required tools (`get_customer`, `list_customers`, `update_customer`, `create_ticket`, `get_customer_history`) via FastMCP | `mcp_server/server.py` | `python mcp_server/server.py` (starts HTTP at http://localhost:8000/mcp) |
| Database schema with customers/tickets and seeding | `mcp_server/server.py` (`CustomerStore.initialize`) | Inspect file; DB created at `mcp_server/support.db` when running demo |
| A2A coordination with explicit logging | `src/agents/base.py` (`ConversationLog`), used across agents | `python demo.py` prints hop-by-hop log per scenario |
| Scenario 1: Task allocation (fetch customer then support) | `RouterAgent._scenario_upgrade` / `_scenario_get_customer`; demo scenario 1 & 2 | `python demo.py` (Scenario 1/2 output) |
| Scenario 2: Negotiation/escalation | `RouterAgent._scenario_escalation` with support ticket creation | `python demo.py` (Scenario 4 output) |
| Scenario 3: Multi-step coordination (premium/high-priority report) | `RouterAgent._scenario_high_priority_report` | `python demo.py` (Scenario 6 output) |
| Test: Simple query (single agent) | Demo scenario 1 (`Get customer information for ID 1`) | `python demo.py` |
| Test: Coordinated query (upgrade) | Demo scenario 2 | `python demo.py` |
| Test: Complex query (active customers with open tickets) | Demo scenario 3 | `python demo.py` |
| Test: Escalation (urgent refund) | Demo scenario 4 | `python demo.py` |
| Test: Multi-intent (update email + history) | Demo scenario 5 | `python demo.py` |
| Deliverable: README with setup and explanation | `README.md` | Read file; includes conclusion and setup steps |
| Deliverable: End-to-end runnable program | `demo.py` | `python demo.py` resets DB, runs scenarios, prints logs |
