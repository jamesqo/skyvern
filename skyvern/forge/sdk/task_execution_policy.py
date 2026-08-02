"""Deterministic runtime limits for autonomous browser tasks.

Policies travel inside ``navigation_payload`` so they survive existing task
persistence without a Skyvern database migration. The reserved key is removed
from prompts separately; callers should treat it as runtime metadata, not form
data.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

EXECUTION_POLICY_KEY = "__skyvern_execution_policy__"


class TaskExecutionPolicy(BaseModel):
    """Hard limits enforced by browser runtime rather than by prompting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allow_final_submit: bool = True
    allow_captcha_wait: bool = True
    max_open_pages: int | None = Field(default=None, ge=1)
    max_action_attempts: int | None = Field(default=None, ge=1)
    require_review_ready: bool = False
    require_verified_upload: bool = False


DEFAULT_EXECUTION_POLICY = TaskExecutionPolicy()


def parse_task_execution_policy(payload: object) -> TaskExecutionPolicy:
    """Return validated policy embedded in a navigation payload.

    Missing policy preserves upstream Skyvern behavior. An explicitly supplied
    malformed policy fails validation instead of silently weakening limits.
    """

    if not isinstance(payload, dict) or EXECUTION_POLICY_KEY not in payload:
        return DEFAULT_EXECUTION_POLICY

    raw_policy: Any = payload[EXECUTION_POLICY_KEY]
    return TaskExecutionPolicy.model_validate(raw_policy)


def prompt_navigation_payload(payload: object) -> object:
    """Remove runtime-only policy metadata before sending profile data to an LLM."""

    if not isinstance(payload, dict) or EXECUTION_POLICY_KEY not in payload:
        return payload
    return {key: value for key, value in payload.items() if key != EXECUTION_POLICY_KEY}


def embed_task_execution_policy(
    payload: object,
    policy: TaskExecutionPolicy | None,
) -> object:
    """Persist an explicit policy alongside generated task navigation data."""

    if policy is None:
        return payload
    result = dict(payload) if isinstance(payload, dict) else {}
    result[EXECUTION_POLICY_KEY] = policy.model_dump(exclude_none=True, exclude_defaults=True)
    return result
