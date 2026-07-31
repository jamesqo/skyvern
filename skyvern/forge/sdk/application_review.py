"""Read-only, deterministic review-readiness audit for application forms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.async_api import Frame, Page

_FRAME_AUDIT_SCRIPT = r"""
() => {
    const visible = (element) => {
        const style = getComputedStyle(element);
        return style.display !== "none"
            && style.visibility !== "hidden"
            && Number(style.opacity || "1") !== 0
            && element.getClientRects().length > 0;
    };
    const normalizedLabel = (element) => [
        element.innerText,
        element.value,
        element.getAttribute("aria-label"),
        element.getAttribute("title"),
    ].filter(Boolean).join(" ").replace(/\s+/g, " ").trim().toLowerCase();
    const finalSubmit = (element) => {
        const label = normalizedLabel(element);
        return /(^|\b)(submit|send application|complete application|finish application|apply now)(\b|$)/.test(label)
            || label === "apply";
    };
    const fieldText = (field) => [
        field.name,
        field.id,
        field.getAttribute("autocomplete"),
        field.getAttribute("aria-label"),
        field.getAttribute("placeholder"),
    ].filter(Boolean).join(" ").toLowerCase();
    const missing = (field, form) => {
        const tag = field.tagName.toLowerCase();
        const type = (field.getAttribute("type") || "").toLowerCase();
        if (type === "radio") {
            const name = CSS.escape(field.name || "");
            return name ? !form.querySelector(`input[type="radio"][name="${name}"]:checked`) : !field.checked;
        }
        if (type === "checkbox") return !field.checked;
        if (type === "file") return !field.files || field.files.length === 0;
        if (tag === "select") return !field.value || field.selectedOptions[0]?.disabled === true;
        return !(field.value || "").trim();
    };

    const allFinalSubmitControls = Array.from(
        document.querySelectorAll("button, input[type='submit'], [role='button']")
    ).filter((element) => visible(element) && finalSubmit(element));
    const candidates = Array.from(document.querySelectorAll("form")).map((form) => {
        const controls = Array.from(form.querySelectorAll("input, textarea, select")).filter(visible);
        const hasEmail = controls.some((field) => field.type === "email" || /(^|[\s_-])email([\s_-]|$)/.test(fieldText(field)));
        const hasName = controls.some((field) => /(first|last|given|family|full)[\s_-]*name/.test(fieldText(field)));
        const fileInputs = controls.filter((field) => field.type === "file");
        const ownedSubmitControls = allFinalSubmitControls.filter((element) => element.form === form || form.contains(element));
        const submitControls = ownedSubmitControls.length > 0
            ? ownedSubmitControls
            : (allFinalSubmitControls.length === 1 ? allFinalSubmitControls : []);
        const applicationLike = (hasEmail && hasName)
            || (controls.length >= 4 && (fileInputs.length > 0 || submitControls.length > 0));
        if (!applicationLike) return null;

        const required = controls.filter((field) => field.required || field.getAttribute("aria-required") === "true");
        const missingRequired = required.filter((field) => missing(field, form));
        const invalid = controls.filter((field) =>
            field.getAttribute("aria-invalid") === "true" || (field.matches(":invalid") && !missing(field, form))
        );
        const attachedFiles = fileInputs.filter((field) => field.files && field.files.length > 0);
        return {
            form,
            audit: {
                score: controls.length + (hasEmail ? 10 : 0) + (hasName ? 10 : 0) + (fileInputs.length ? 5 : 0),
                required_control_count: required.length,
                missing_required_count: missingRequired.length,
                invalid_control_count: invalid.length,
                file_input_count: fileInputs.length,
                attached_file_input_count: attachedFiles.length,
                final_submit_count: submitControls.length,
            },
        };
    }).filter(Boolean);

    const applicationForms = new Set(candidates.map((candidate) => candidate.form));
    const blockingDialogs = Array.from(document.querySelectorAll("dialog[open], [role='dialog'][aria-modal='true']"))
        .filter((dialog) => visible(dialog) && !Array.from(dialog.querySelectorAll("form")).some((form) => applicationForms.has(form)));
    candidates.sort((left, right) => right.audit.score - left.audit.score);
    return {best: candidates[0]?.audit || null, blocking_dialog_count: blockingDialogs.length};
}
"""


@dataclass(frozen=True, slots=True)
class ApplicationReviewReadiness:
    """Safe aggregate evidence used to accept or veto agent completion."""

    ready: bool
    form_found: bool
    required_control_count: int
    missing_required_count: int
    invalid_control_count: int
    file_input_count: int
    attached_file_input_count: int
    final_submit_count: int
    blocking_dialog_count: int
    upload_verified: bool


async def _audit_frame(frame: Frame) -> dict[str, Any] | None:
    try:
        result = await frame.evaluate(_FRAME_AUDIT_SCRIPT)
    except Exception:
        return None
    return result if isinstance(result, dict) else None


async def audit_application_review(
    page: Page,
    *,
    require_verified_upload: bool,
    upload_verified: bool,
) -> ApplicationReviewReadiness:
    """Audit every frame, choosing strongest application form without exposing field data."""

    await page.wait_for_timeout(750)
    frame_results = [result for frame in page.frames if (result := await _audit_frame(frame)) is not None]
    candidates = [result["best"] for result in frame_results if isinstance(result.get("best"), dict)]
    best = max(candidates, key=lambda candidate: int(candidate.get("score", 0)), default=None)
    blocking_dialog_count = sum(int(result.get("blocking_dialog_count", 0)) for result in frame_results)

    if best is None:
        return ApplicationReviewReadiness(
            ready=False,
            form_found=False,
            required_control_count=0,
            missing_required_count=0,
            invalid_control_count=0,
            file_input_count=0,
            attached_file_input_count=0,
            final_submit_count=0,
            blocking_dialog_count=blocking_dialog_count,
            upload_verified=upload_verified,
        )

    required_control_count = int(best.get("required_control_count", 0))
    missing_required_count = int(best.get("missing_required_count", 0))
    invalid_control_count = int(best.get("invalid_control_count", 0))
    file_input_count = int(best.get("file_input_count", 0))
    attached_file_input_count = int(best.get("attached_file_input_count", 0))
    final_submit_count = int(best.get("final_submit_count", 0))
    attachment_ready = not require_verified_upload or upload_verified or attached_file_input_count > 0
    ready = (
        missing_required_count == 0
        and invalid_control_count == 0
        and final_submit_count > 0
        and blocking_dialog_count == 0
        and attachment_ready
    )
    return ApplicationReviewReadiness(
        ready=ready,
        form_found=True,
        required_control_count=required_control_count,
        missing_required_count=missing_required_count,
        invalid_control_count=invalid_control_count,
        file_input_count=file_input_count,
        attached_file_input_count=attached_file_input_count,
        final_submit_count=final_submit_count,
        blocking_dialog_count=blocking_dialog_count,
        upload_verified=upload_verified,
    )
