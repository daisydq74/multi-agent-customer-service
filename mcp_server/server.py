from __future__ import annotations

import dataclasses
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from database_setup import DatabaseSetup

DB_PATH = Path(__file__).resolve().parent / "support.db"
ALLOWED_CUSTOMER_FIELDS = {"name", "email", "phone", "status"}
ALLOWED_CUSTOMER_STATUS = {"active", "disabled"}
ALLOWED_TICKET_PRIORITY = {"low", "medium", "high"}

# Configure stderr logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_server")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_database() -> None:
    if not DB_PATH.exists():
        logger.info("Initializing SQLite database at %s", DB_PATH)
    DatabaseSetup(DB_PATH).initialize()
    _ensure_customer_columns(["phone TEXT", "updated_at TEXT DEFAULT CURRENT_TIMESTAMP"])


def _validate_customer_id(customer_id: int) -> None:
    if not isinstance(customer_id, int) or customer_id <= 0:
        raise ValueError("customer_id must be a positive integer")


def _validate_status(status: Optional[str]) -> None:
    if status is None:
        return
    if status not in ALLOWED_CUSTOMER_STATUS:
        raise ValueError(f"status must be one of {sorted(ALLOWED_CUSTOMER_STATUS)}")


def _validate_priority(priority: str) -> None:
    if priority not in ALLOWED_TICKET_PRIORITY:
        raise ValueError(f"priority must be one of {sorted(ALLOWED_TICKET_PRIORITY)}")


def _validate_limit(limit: int) -> None:
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if limit > 100:
        raise ValueError("limit too high; must be <= 100")


def _ensure_customer_columns(column_defs: List[str]) -> None:
    """Add missing columns to customers to match assignment schema."""
    with get_connection() as conn:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(customers)")}
        for col_def in column_defs:
            name = col_def.split()[0]
            if name not in existing:
                logger.info("Adding missing column to customers: %s", col_def)
                # SQLite only allows constant defaults on ALTER TABLE; set dynamic defaults manually.
                if name == "updated_at":
                    conn.execute("ALTER TABLE customers ADD COLUMN updated_at TEXT")
                    conn.execute("UPDATE customers SET updated_at = CURRENT_TIMESTAMP")
                else:
                    conn.execute(f"ALTER TABLE customers ADD COLUMN {col_def}")
        conn.commit()


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


mcp = FastMCP("customer-mcp")


@dataclasses.dataclass
class ToolCall:
    name: str
    args: Dict[str, Any]


@dataclasses.dataclass
class ToolResult:
    call: ToolCall
    result: Any
    error: Optional[str] = None


@mcp.tool()
def get_customer(customer_id: int) -> Dict[str, Any]:
    """Fetch a single customer by id."""
    logger.info("get_customer called with customer_id=%s", customer_id)
    ensure_database()
    try:
        _validate_customer_id(customer_id)
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, name, email, phone, status, created_at, updated_at
                FROM customers
                WHERE id = ?
                """,
                (customer_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Customer {customer_id} not found")
            return row_to_dict(row)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("get_customer failed: %s", exc)
        raise


@mcp.tool()
def list_customers(status: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """List customers by status with a limit."""
    logger.info("list_customers called with status=%s, limit=%s", status, limit)
    ensure_database()
    try:
        _validate_status(status)
        _validate_limit(limit)
        with get_connection() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT id, name, email, phone, status, created_at, updated_at
                    FROM customers
                    WHERE status = ?
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, name, email, phone, status, created_at, updated_at
                    FROM customers
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [row_to_dict(row) for row in rows]
    except Exception as exc:  # pragma: no cover
        logger.exception("list_customers failed: %s", exc)
        raise


@mcp.tool()
def update_customer(customer_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update allowed fields for a customer record."""
    logger.info("update_customer called with customer_id=%s data=%s", customer_id, data)
    ensure_database()
    try:
        _validate_customer_id(customer_id)
        updates = {k: v for k, v in data.items() if k in ALLOWED_CUSTOMER_FIELDS}
        if not updates:
            raise ValueError("No valid fields to update")
        if "status" in updates:
            _validate_status(updates["status"])

        set_clause = ", ".join(f"{key} = ?" for key in updates.keys())
        values = list(updates.values())
        values.append(customer_id)

        with get_connection() as conn:
            cur = conn.execute(
                f"UPDATE customers SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
            if cur.rowcount == 0:
                raise ValueError(f"Customer {customer_id} not found")
            conn.commit()

        return get_customer(customer_id)
    except Exception as exc:  # pragma: no cover
        logger.exception("update_customer failed: %s", exc)
        raise


@mcp.tool()
def create_ticket(customer_id: int, issue: str, priority: str = "medium") -> Dict[str, Any]:
    """Create a ticket for a customer."""
    logger.info(
        "create_ticket called with customer_id=%s issue=%s priority=%s",
        customer_id,
        issue,
        priority,
    )
    ensure_database()
    try:
        _validate_customer_id(customer_id)
        if not issue or not issue.strip():
            raise ValueError("issue is required")
        _validate_priority(priority)
        with get_connection() as conn:
            # Ensure customer exists
            exists = conn.execute(
                "SELECT 1 FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
            if not exists:
                raise ValueError(f"Customer {customer_id} not found")

            conn.execute(
                """
                INSERT INTO tickets (customer_id, issue, status, priority, created_at)
                VALUES (?, ?, 'open', ?, CURRENT_TIMESTAMP)
                """,
                (customer_id, issue, priority),
            )
            ticket_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            row = conn.execute(
                """
                SELECT id, customer_id, issue, status, priority, created_at
                FROM tickets
                WHERE id = ?
                """,
                (ticket_id,),
            ).fetchone()
            return row_to_dict(row)
    except Exception as exc:  # pragma: no cover
        logger.exception("create_ticket failed: %s", exc)
        raise


@mcp.tool()
def get_customer_history(customer_id: int) -> List[Dict[str, Any]]:
    """Return ticket history for a customer."""
    logger.info("get_customer_history called with customer_id=%s", customer_id)
    ensure_database()
    try:
        _validate_customer_id(customer_id)
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, customer_id, issue, status, priority, created_at
                FROM tickets
                WHERE customer_id = ?
                ORDER BY created_at DESC
                """,
                (customer_id,),
            ).fetchall()
            return [row_to_dict(row) for row in rows]
    except Exception as exc:  # pragma: no cover
        logger.exception("get_customer_history failed: %s", exc)
        raise


class MCPServer:
    """
    Lightweight compatibility layer so local agents/demo can call tools
    without running the HTTP transport.
    """

    def __init__(self) -> None:
        ensure_database()

    def get_customer(self, customer_id: int) -> ToolResult:
        call = ToolCall("get_customer", {"customer_id": customer_id})
        try:
            return ToolResult(call, result=get_customer(customer_id))
        except Exception as exc:
            return ToolResult(call, result=None, error=str(exc))

    def list_customers(self, status: Optional[str] = None, limit: int = 10) -> ToolResult:
        call = ToolCall("list_customers", {"status": status, "limit": limit})
        try:
            return ToolResult(call, result=list_customers(status=status, limit=limit))
        except Exception as exc:
            return ToolResult(call, result=None, error=str(exc))

    def update_customer(self, customer_id: int, data: Dict[str, Any]) -> ToolResult:
        call = ToolCall("update_customer", {"customer_id": customer_id, "data": data})
        try:
            return ToolResult(call, result=update_customer(customer_id, data))
        except Exception as exc:
            return ToolResult(call, result=None, error=str(exc))

    def create_ticket(self, customer_id: int, issue: str, priority: str = "medium") -> ToolResult:
        call = ToolCall(
            "create_ticket", {"customer_id": customer_id, "issue": issue, "priority": priority}
        )
        try:
            return ToolResult(call, result=create_ticket(customer_id, issue, priority))
        except Exception as exc:
            return ToolResult(call, result=None, error=str(exc))

    def get_customer_history(self, customer_id: int) -> ToolResult:
        call = ToolCall("get_customer_history", {"customer_id": customer_id})
        try:
            return ToolResult(call, result=get_customer_history(customer_id))
        except Exception as exc:
            return ToolResult(call, result=None, error=str(exc))


def reset_database() -> None:
    """Drop and recreate tables using the provided setup helper."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    ensure_database()


if __name__ == "__main__":
    ensure_database()
    logger.info("Starting MCP server at http://localhost:8000/mcp")
    mcp.run_http(host="0.0.0.0", port=8000, path="/mcp")
