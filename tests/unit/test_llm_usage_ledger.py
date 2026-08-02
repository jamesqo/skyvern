"""Append-only provider usage ledger tests."""

from __future__ import annotations

import json

from skyvern.forge.sdk.api.llm.usage_ledger import LEDGER_PATH_ENV, append_usage


def test_append_usage_writes_run_scoped_provider_measurement(tmp_path, monkeypatch) -> None:
    ledger = tmp_path / "usage" / "ledger.jsonl"
    monkeypatch.setenv(LEDGER_PATH_ENV, str(ledger))

    append_usage(
        task_id="task-1",
        response_id="response-1",
        model="openai/gpt-mini",
        prompt_name="extract-actions",
        cost_usd=0.0123,
        cost_known=True,
        input_tokens=100,
        output_tokens=20,
        reasoning_tokens=3,
        cached_tokens=7,
    )

    event = json.loads(ledger.read_text().strip())
    assert event["task_id"] == "task-1"
    assert event["response_id"] == "response-1"
    assert event["cost_usd"] == 0.0123
    assert event["cost_known"] is True
    assert event["input_tokens"] == 100


def test_append_usage_is_disabled_without_path(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(LEDGER_PATH_ENV, raising=False)

    append_usage(
        task_id="task-1",
        response_id=None,
        model="model",
        prompt_name="prompt",
        cost_usd=1.0,
        cost_known=False,
        input_tokens=1,
        output_tokens=1,
        reasoning_tokens=0,
        cached_tokens=0,
    )

    assert list(tmp_path.iterdir()) == []
