from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is on sys.path so imports resolve when run directly
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.server import DB_PATH, ensure_database

# Configure logging to mirror server output style
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ensure_seed_data")


def _ensure_customers(conn: sqlite3.Connection) -> None:
    """Ensure required seed customers exist."""
    seed_customers: List[Dict[str, str]] = [
        {
            "id": 5,
            "name": "Customer Five",
            "email": "customer5@example.com",
            "phone": "+1-555-0005",
            "status": "active",
        },
        {
            "id": 12345,
            "name": "Customer 12345",
            "email": "customer12345@example.com",
            "phone": "+1-555-12345",
            "status": "active",
        },
    ]

    for cust in seed_customers:
        exists = conn.execute("SELECT 1 FROM customers WHERE id = ?", (cust["id"],)).fetchone()
        if exists:
            logger.info("Customer %s already exists", cust["id"])
            continue
        conn.execute(
            """
            INSERT INTO customers (id, name, email, phone, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (cust["id"], cust["name"], cust["email"], cust["phone"], cust["status"]),
        )
        logger.info(
            "Inserted customer %s (%s, %s, %s)",
            cust["id"],
            cust["name"],
            cust["email"],
            cust["phone"],
        )


def _ensure_high_priority_ticket(conn: sqlite3.Connection, customer_id: int) -> None:
    """Ensure the customer has at least one open high-priority ticket."""
    existing = conn.execute(
        """
        SELECT id FROM tickets
        WHERE customer_id = ? AND status = 'open' AND priority = 'high'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (customer_id,),
    ).fetchone()
    if existing:
        logger.info(
            "Customer %s already has an open high-priority ticket (id=%s)",
            customer_id,
            existing["id"] if isinstance(existing, sqlite3.Row) else existing[0],
        )
        return

    conn.execute(
        """
        INSERT INTO tickets (customer_id, issue, status, priority, created_at)
        VALUES (?, ?, 'open', 'high', CURRENT_TIMESTAMP)
        """,
        (customer_id, "Seeded high-priority ticket"),
    )
    ticket_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    logger.info("Inserted high-priority open ticket %s for customer %s", ticket_id, customer_id)


def _ensure_active_open_ticket(conn: sqlite3.Connection) -> None:
    """Guarantee at least one open ticket exists for an active customer."""
    existing = conn.execute(
        """
        SELECT t.id FROM tickets t
        JOIN customers c ON c.id = t.customer_id
        WHERE c.status = 'active' AND t.status = 'open'
        LIMIT 1
        """,
    ).fetchone()
    if existing:
        logger.info("Active customer already has an open ticket (ticket id=%s)", existing[0])
        return

    active_customer = conn.execute(
        "SELECT id FROM customers WHERE status = 'active' ORDER BY id LIMIT 1"
    ).fetchone()
    if not active_customer:
        logger.warning("No active customers found; cannot seed open ticket")
        return

    conn.execute(
        """
        INSERT INTO tickets (customer_id, issue, status, priority, created_at)
        VALUES (?, ?, 'open', 'medium', CURRENT_TIMESTAMP)
        """,
        (active_customer[0], "Seeded open ticket for active customer"),
    )
    ticket_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    logger.info(
        "Inserted open ticket %s for active customer %s", ticket_id, active_customer[0]
    )


def ensure_required_records(db_path: Optional[str | Path] = None) -> None:
    """Ensure required customers and tickets exist; safe to run multiple times."""
    target = Path(db_path) if db_path else DB_PATH
    ensure_database()
    with sqlite3.connect(target) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _ensure_customers(conn)
        _ensure_high_priority_ticket(conn, 12345)
        _ensure_active_open_ticket(conn)
        conn.commit()


def ensure_seed_data() -> None:
    """Backward-compatible entry point."""
    ensure_required_records(DB_PATH)


if __name__ == "__main__":
    ensure_seed_data()
