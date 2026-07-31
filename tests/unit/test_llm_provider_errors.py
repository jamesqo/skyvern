from types import SimpleNamespace

import pytest

from skyvern.forge.sdk.api.llm.exceptions import (
    is_retryable_provider_error,
    provider_error_status_code,
)


class ProviderError(Exception):
    def __init__(self, status_code: int | None = None) -> None:
        super().__init__(f"provider status {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (None, True),
        (400, False),
        (401, False),
        (402, False),
        (403, False),
        (408, True),
        (429, True),
        (500, True),
        (503, True),
    ],
)
def test_provider_error_retryability(status_code: int | None, expected: bool) -> None:
    assert is_retryable_provider_error(ProviderError(status_code)) is expected


def test_provider_error_status_code_falls_back_to_response() -> None:
    class ResponseProviderError(Exception):
        response = SimpleNamespace(status_code=402)

    assert provider_error_status_code(ResponseProviderError()) == 402
