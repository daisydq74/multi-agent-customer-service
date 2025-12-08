from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.ensure_seed_data import ensure_required_records  # noqa: E402
from mcp_server.server import DB_PATH, reset_database  # noqa: E402
from src.a2a.client import A2ASimpleClient  # noqa: E402

PYTHONPATH = os.environ.get("PYTHONPATH", "")
ENV = {**os.environ, "PYTHONPATH": f"{ROOT}:{PYTHONPATH}" if PYTHONPATH else str(ROOT)}

SERVICES: List[List[str]] = [
    ["python", "-m", "uvicorn", "services.customer_data_server:app", "--host", "0.0.0.0", "--port", "8011"],
    ["python", "-m", "uvicorn", "services.support_server:app", "--host", "0.0.0.0", "--port", "8012"],
    ["python", "-m", "uvicorn", "services.router_server:app", "--host", "0.0.0.0", "--port", "8010"],
]

SCENARIOS = [
    "Get customer information for ID 5",
    "I'm customer 12345 and need help upgrading my account",
    "Show me all active customers who have open tickets",
    "I've been charged twice, please refund immediately!",
    "I'm customer 1. Update my email to new@email.com and show my ticket history",
]


def _print_heading(title: str) -> None:
    print("\n" + title)
    print("=" * len(title))


def _env_banner() -> str:
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    router_model = os.getenv("OPENAI_MODEL_ROUTER", "gpt-4o-mini")
    data_model = os.getenv("OPENAI_MODEL_DATA", "gpt-4o-mini")
    support_model = os.getenv("OPENAI_MODEL_SUPPORT") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    banner_lines = [
        "OpenAI configuration:",
        f"- OPENAI_API_KEY set: {has_key}",
        f"- Router model: {router_model}",
        f"- Data model: {data_model}",
        f"- Support model: {support_model}",
    ]
    for line in banner_lines:
        print(line)
    return "\n".join(banner_lines)


def _format_meta(meta: Dict[str, object]) -> str:
    used = meta.get("used_llm", False)
    model = meta.get("model", "none")
    temperature = meta.get("temperature", "none")
    return f"used_llm={used}, model={model}, temperature={temperature}"


async def _start_services() -> List[asyncio.subprocess.Process]:
    procs: List[asyncio.subprocess.Process] = []
    for cmd in SERVICES:
        proc = await asyncio.create_subprocess_exec(*cmd, env=ENV)
        procs.append(proc)
    return procs


async def _stop_services(procs: List[asyncio.subprocess.Process]) -> None:
    for proc in procs:
        if proc.returncode is None:
            proc.send_signal(signal.SIGTERM)
    await asyncio.gather(*(proc.wait() for proc in procs))


async def _wait_for_services() -> None:
    clients = [
        A2ASimpleClient("http://localhost:8011"),
        A2ASimpleClient("http://localhost:8012"),
        A2ASimpleClient("http://localhost:8010"),
    ]
    await asyncio.gather(*(client.wait_until_ready() for client in clients))


async def run_demo() -> None:
    reset_database()
    ensure_required_records(DB_PATH)

    procs = await _start_services()
    transcript_path = Path("demos/output/run_a2a_spec.log")
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_lines: List[str] = []

    try:
        await _wait_for_services()
        router_client = A2ASimpleClient("http://localhost:8010")

        _print_heading("Running A2A Spec Demo")
        transcript_lines.append("Running A2A Spec Demo")
        transcript_lines.append(_env_banner())
        for idx, scenario in enumerate(SCENARIOS, start=1):
            print(f"\nScenario {idx}: {scenario}")
            result: Dict[str, Any] = await router_client.send_message(scenario)
            response = result.get("response", "")
            log = result.get("log", "")
            meta = result.get("meta", {})
            print("Response:", response)
            print("A2A Log:\n", log)
            print(f"LLM Meta: {_format_meta(meta)}")

            transcript_lines.append(f"Scenario {idx}: {scenario}")
            transcript_lines.append(f"Response: {response}")
            transcript_lines.append("A2A Log:")
            transcript_lines.append(log)
            transcript_lines.append(f"LLM Meta: {_format_meta(meta)}")
            transcript_lines.append("")

        transcript_path.write_text("\n".join(transcript_lines), encoding="utf-8")
    finally:
        await _stop_services(procs)


if __name__ == "__main__":
    asyncio.run(run_demo())
