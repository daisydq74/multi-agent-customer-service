from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional

import httpx


class A2ASimpleClient:
    """Tiny helper to call A2A-spec services via JSON-RPC."""

    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def fetch_agent_card(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/.well-known/agent-card.json")
            resp.raise_for_status()
            return resp.json()

    async def send_message(self, message: Any, *, card: Optional[Dict[str, Any]] = None) -> Any:
        card_data = card or await self.fetch_agent_card()
        rpc_url = (
            card_data.get("rpc", {}).get("url")
            or card_data.get("message_url")
            or f"{self.base_url}/rpc"
        )
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {"message": message},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data.get("result", {}).get("message")

    async def wait_until_ready(self, *, attempts: int = 20, delay: float = 0.5) -> None:
        last_error: Optional[Exception] = None
        for _ in range(attempts):
            try:
                await self.fetch_agent_card()
                return
            except Exception as exc:  # pragma: no cover - simple retry loop
                last_error = exc
                await asyncio.sleep(delay)
        if last_error:
            raise last_error

