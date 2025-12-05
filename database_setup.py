from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Tuple


class DatabaseSetup:
    """Helper to initialize the Assignment 5 SQLite database."""

    def __init__(self, db_path: Path | str = "support.db") -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        """Create tables and seed sample data if empty."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    issue TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(customer_id) REFERENCES customers(id)
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(customer_id) REFERENCES customers(id)
                );
                """
            )
            conn.commit()

            cursor = conn.execute("SELECT COUNT(*) FROM customers")
            count = cursor.fetchone()[0]
            if count == 0:
                customers: Iterable[Tuple[str, str, str]] = [
                    ("Ana Customer", "ana@example.com", "active"),
                    ("Brian Blocked", "brian@example.com", "delinquent"),
                    ("Cara Care", "cara@example.com", "vip"),
                ]
                interactions: Iterable[Tuple[int, str, str]] = [
                    (1, "email", "Welcome email sent"),
                    (1, "phone", "Reported login issue"),
                    (2, "chat", "Billing dispute opened"),
                    (3, "email", "Requested feature roadmap"),
                ]
                conn.executemany(
                    "INSERT INTO customers(name, email, status) VALUES(?,?,?)",
                    customers,
                )
                conn.executemany(
                    "INSERT INTO interactions(customer_id, channel, notes) VALUES(?,?,?)",
                    interactions,
                )
                conn.commit()


if __name__ == "__main__":
    DatabaseSetup().initialize()
    print("Database initialized at support.db")
