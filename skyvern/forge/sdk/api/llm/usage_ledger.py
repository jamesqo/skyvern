"""Failure-safe append-only LLM usage ledger for external run accounting."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import structlog

LOG = structlog.get_logger()
LEDGER_PATH_ENV = "SKYVERN_LLM_USAGE_LEDGER_PATH"


def append_usage(
    *,
    task_id: str | None,
    response_id: str | None,
    model: str,
    prompt_name: str,
    cost_usd: float,
    cost_known: bool,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    cached_tokens: int,
) -> None:
    """Append one successful provider response; telemetry failure never fails a task."""

    configured_path = os.environ.get(LEDGER_PATH_ENV)
    if not configured_path or not task_id:
        return

    event: dict[str, Any] = {
        "timestamp": time.time(),
        "task_id": task_id,
        "response_id": response_id,
        "model": model,
        "prompt_name": prompt_name,
        "cost_usd": max(0.0, cost_usd),
        "cost_known": cost_known,
        "input_tokens": max(0, input_tokens),
        "output_tokens": max(0, output_tokens),
        "reasoning_tokens": max(0, reasoning_tokens),
        "cached_tokens": max(0, cached_tokens),
    }
    try:
        path = Path(configured_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(event, separators=(",", ":")) + "\n").encode()
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)
    except Exception:
        LOG.warning("Failed to append LLM usage ledger", task_id=task_id, exc_info=True)
