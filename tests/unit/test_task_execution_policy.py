"""Hard autonomous task execution policy tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from skyvern.forge.sdk.core import skyvern_context
from skyvern.forge.sdk.core.skyvern_context import SkyvernContext
from skyvern.forge.sdk.schemas.tasks import TaskRequest
from skyvern.forge.sdk.task_execution_policy import (
    EXECUTION_POLICY_KEY,
    TaskExecutionPolicy,
    embed_task_execution_policy,
    parse_task_execution_policy,
    prompt_navigation_payload,
)
from skyvern.webeye.actions import handler as handler_module
from skyvern.webeye.actions.actions import ExecuteJsAction, InputTextAction, NewTabAction
from skyvern.webeye.actions.responses import ActionFailure, ActionSuccess


def _payload(**policy: object) -> dict[str, object]:
    return {"first_name": "Ada", EXECUTION_POLICY_KEY: policy}


def test_missing_policy_preserves_upstream_behavior() -> None:
    policy = parse_task_execution_policy({"first_name": "Ada"})

    assert policy.allow_final_submit is True
    assert policy.max_open_pages is None
    assert policy.max_action_attempts is None
    assert policy.require_review_ready is False
    assert policy.require_verified_upload is False


def test_policy_metadata_is_removed_from_prompt_payload() -> None:
    payload = _payload(allow_final_submit=False, max_open_pages=1)

    assert prompt_navigation_payload(payload) == {"first_name": "Ada"}
    assert EXECUTION_POLICY_KEY in payload


def test_policy_is_embedded_without_mutating_generated_payload() -> None:
    payload = {"first_name": "Ada"}
    policy = TaskExecutionPolicy(allow_final_submit=False, max_open_pages=1)

    embedded = embed_task_execution_policy(payload, policy)

    assert embedded == _payload(allow_final_submit=False, max_open_pages=1)
    assert payload == {"first_name": "Ada"}


def test_task_request_rejects_malformed_policy() -> None:
    with pytest.raises(ValidationError):
        TaskRequest(
            url="https://example.test",
            navigation_payload=_payload(max_open_pages=0),
        )


def test_single_page_policy_blocks_new_tab_action() -> None:
    task = MagicMock(navigation_payload=_payload(max_open_pages=1))

    assert handler_module._execution_policy_violation(task, NewTabAction(url="https://example.test")) == "new_tab"


def test_no_submit_policy_blocks_execute_js() -> None:
    task = MagicMock(navigation_payload=_payload(allow_final_submit=False))

    assert handler_module._execution_policy_violation(task, ExecuteJsAction(js_code="form.submit()")) == "execute_js"


@pytest.mark.asyncio
async def test_no_submit_policy_blocks_final_submission_control() -> None:
    task = MagicMock(navigation_payload=_payload(allow_final_submit=False))
    locator = MagicMock(evaluate=AsyncMock(return_value=True))

    assert await handler_module._final_submission_blocked(task, locator) is True


@pytest.mark.asyncio
async def test_no_submit_policy_allows_continue_control() -> None:
    task = MagicMock(navigation_payload=_payload(allow_final_submit=False))
    locator = MagicMock(evaluate=AsyncMock(return_value=False))

    assert await handler_module._final_submission_blocked(task, locator) is False


@pytest.mark.asyncio
async def test_no_submit_policy_blocks_enter_inside_form() -> None:
    task = MagicMock(navigation_payload=_payload(allow_final_submit=False))
    page = MagicMock(evaluate=AsyncMock(return_value=True))

    assert await handler_module._enter_submission_blocked(task, page, ["Enter"]) is True


@pytest.mark.asyncio
async def test_no_submit_policy_blocks_coordinate_click_on_final_submit() -> None:
    task = MagicMock(navigation_payload=_payload(allow_final_submit=False))
    page = MagicMock(evaluate=AsyncMock(return_value=True))

    assert await handler_module._coordinate_submission_blocked(task, page, 10, 20) is True


@pytest.mark.asyncio
async def test_single_page_policy_closes_oldest_page_and_activates_newest() -> None:
    task = MagicMock(navigation_payload=_payload(max_open_pages=1))
    old_page = MagicMock(is_closed=MagicMock(return_value=False), close=AsyncMock())
    new_page = MagicMock(is_closed=MagicMock(return_value=False), close=AsyncMock())
    old_page.context.pages = [old_page, new_page]
    browser_state = MagicMock(set_active_page=AsyncMock())

    closed = await handler_module._enforce_open_page_limit(task, browser_state, old_page)

    assert closed == 1
    old_page.close.assert_awaited_once_with()
    new_page.close.assert_not_awaited()
    browser_state.set_active_page.assert_awaited_once_with(new_page)


def test_repeated_failed_action_is_blocked_at_configured_attempt_limit() -> None:
    task = MagicMock(
        task_id="task-1",
        navigation_payload=_payload(max_action_attempts=2),
    )
    action = InputTextAction(element_id="field-1", text="private value")
    context = SkyvernContext()

    with skyvern_context.scoped(context):
        fingerprint = handler_module._action_retry_fingerprint(task, action)
        assert fingerprint is not None
        assert "private value" not in fingerprint
        handler_module._record_action_attempt(task, fingerprint, [ActionFailure(RuntimeError("failed"))])
        assert handler_module._retry_policy_violation(task, fingerprint) is None
        handler_module._record_action_attempt(task, fingerprint, [ActionFailure(RuntimeError("failed"))])
        assert handler_module._retry_policy_violation(task, fingerprint) == "repeated_action"
        handler_module._record_action_attempt(task, fingerprint, [ActionSuccess()])
        assert handler_module._retry_policy_violation(task, fingerprint) is None
