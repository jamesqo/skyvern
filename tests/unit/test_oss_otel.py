from unittest.mock import patch

from skyvern.forge.sdk.trace import oss_otel


def test_safe_span_attributes_drops_sensitive_values() -> None:
    attributes = {
        "code.function": "handler",
        "gen_ai.request.model": "test-model",
        "http.url": "https://example.test/application?token=secret",
        "resume.path": "/private/resume.pdf",
        "exception.message": "secret",
    }

    assert oss_otel.safe_span_attributes(attributes) == {
        "code.function": "handler",
        "gen_ai.request.model": "test-model",
    }


def test_initialize_oss_otel_contains_setup_failures() -> None:
    with (
        patch.object(oss_otel, "_initialized", False),
        patch(
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter",
            side_effect=RuntimeError("collector unavailable"),
        ),
    ):
        assert oss_otel.initialize_oss_otel() is False
