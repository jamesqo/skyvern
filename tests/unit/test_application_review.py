"""Deterministic application review-readiness tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skyvern.forge.agent_functions import AgentFunction
from skyvern.forge.sdk.application_review import ApplicationReviewReadiness, audit_application_review
from skyvern.forge.sdk.task_execution_policy import EXECUTION_POLICY_KEY


def _frame_result(**overrides: int) -> dict[str, object]:
    best = {
        "score": 30,
        "required_control_count": 5,
        "missing_required_count": 0,
        "invalid_control_count": 0,
        "file_input_count": 1,
        "attached_file_input_count": 1,
        "final_submit_count": 1,
    }
    best.update(overrides)
    return {"best": best, "blocking_dialog_count": 0}


def _page(*results: dict[str, object] | Exception) -> MagicMock:
    frames = []
    for result in results:
        evaluate = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
        frames.append(MagicMock(evaluate=evaluate))
    return MagicMock(frames=frames, wait_for_timeout=AsyncMock())


@pytest.mark.asyncio
async def test_review_ready_requires_complete_form_and_final_submit() -> None:
    page = _page(_frame_result())

    result = await audit_application_review(page, require_verified_upload=True, upload_verified=True)

    assert result.ready is True
    assert result.form_found is True
    assert result.required_control_count == 5
    page.wait_for_timeout.assert_awaited_once_with(750)


@pytest.mark.asyncio
async def test_review_ready_rejects_missing_required_control() -> None:
    page = _page(_frame_result(missing_required_count=1))

    result = await audit_application_review(page, require_verified_upload=False, upload_verified=False)

    assert result.ready is False
    assert result.missing_required_count == 1


@pytest.mark.asyncio
async def test_review_ready_rejects_unverified_required_upload() -> None:
    page = _page(_frame_result(attached_file_input_count=0))

    result = await audit_application_review(page, require_verified_upload=True, upload_verified=False)

    assert result.ready is False
    assert result.upload_verified is False


@pytest.mark.asyncio
async def test_review_audit_uses_strongest_form_across_frames() -> None:
    weak = _frame_result(missing_required_count=2)
    weak["best"]["score"] = 20  # type: ignore[index]
    strong = _frame_result()
    page = _page(RuntimeError("cross-origin frame"), weak, strong)

    result = await audit_application_review(page, require_verified_upload=False, upload_verified=False)

    assert result.ready is True


@pytest.mark.asyncio
async def test_completion_gate_vetoes_non_ready_application() -> None:
    policy = {
        EXECUTION_POLICY_KEY: {
            "allow_final_submit": False,
            "require_review_ready": True,
        }
    }
    task = MagicMock(navigation_payload=policy, task_id="task-1")
    page = MagicMock()
    browser_state = MagicMock(get_working_page=AsyncMock(return_value=page))
    not_ready = ApplicationReviewReadiness(
        ready=False,
        form_found=True,
        required_control_count=4,
        missing_required_count=1,
        invalid_control_count=0,
        file_input_count=1,
        attached_file_input_count=1,
        final_submit_count=1,
        blocking_dialog_count=0,
        upload_verified=True,
    )

    with patch("skyvern.forge.agent_functions.audit_application_review", AsyncMock(return_value=not_ready)):
        accepted = await AgentFunction().gate_step_completion(
            task=task,
            step=MagicMock(),
            task_block=None,
            page=page,
            browser_state=browser_state,
        )

    assert accepted is False
