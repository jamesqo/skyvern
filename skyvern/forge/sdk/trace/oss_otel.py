"""Failure-safe OpenTelemetry bootstrap for self-hosted Skyvern."""

from __future__ import annotations

import atexit
from collections.abc import Collection, Mapping
from typing import Any

import structlog
from opentelemetry import trace

LOG = structlog.get_logger()

_SAFE_ATTRIBUTE_KEYS = frozenset(
    {
        "cache_hit",
        "cached_tokens",
        "code.function",
        "code.namespace",
        "completion_tokens",
        "gen_ai.request.model",
        "gen_ai.usage.cached_tokens",
        "gen_ai.usage.cost",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.reasoning_tokens",
        "image_cost",
        "image_count",
        "image_tokens",
        "latency_ms",
        "llm_cost",
        "llm_model",
        "organization_id",
        "prompt_tokens",
        "reasoning_tokens",
        "skyvern.span.role",
        "status",
        "step_id",
        "task_id",
        "workflow_id",
        "workflow_permanent_id",
        "workflow_run_id",
    }
)

_initialized = False


def safe_span_attributes(
    attributes: Mapping[str, Any] | None,
    *,
    allowed_keys: Collection[str] = _SAFE_ATTRIBUTE_KEYS,
) -> dict[str, Any]:
    """Keep only reviewed low-risk attributes before export."""
    if not attributes:
        return {}
    return {key: value for key, value in attributes.items() if key in allowed_keys}


def initialize_oss_otel() -> bool:
    """Install an OTLP trace provider once; never prevent server startup."""
    global _initialized
    if _initialized:
        return True

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import ReadableSpan, TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import (  # noqa: PLC0415
            BatchSpanProcessor,
            SpanExporter,
        )
        from opentelemetry.trace import Status  # noqa: PLC0415

        from skyvern.config import settings  # noqa: PLC0415

        class SafeSpanExporter(SpanExporter):
            """Strip page, prompt, URL, path, and exception data before export."""

            def __init__(self) -> None:
                self._delegate = OTLPSpanExporter(
                    endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT or None,
                    insecure=settings.OTEL_EXPORTER_INSECURE,
                    timeout=settings.OTEL_EXPORTER_TIMEOUT_SECONDS,
                )

            def export(self, spans: list[ReadableSpan]) -> Any:
                sanitized = [
                    ReadableSpan(
                        name=span.name,
                        context=span.context,
                        parent=span.parent,
                        resource=span.resource,
                        attributes=safe_span_attributes(span.attributes),
                        events=(),
                        links=(),
                        kind=span.kind,
                        instrumentation_scope=span.instrumentation_scope,
                        status=Status(span.status.status_code),
                        start_time=span.start_time,
                        end_time=span.end_time,
                    )
                    for span in spans
                ]
                return self._delegate.export(sanitized)

            def force_flush(self, timeout_millis: int = 30000) -> bool:
                return self._delegate.force_flush(timeout_millis)

            def shutdown(self) -> None:
                self._delegate.shutdown()

        resource = Resource.create({SERVICE_NAME: settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(
                SafeSpanExporter(),
                max_queue_size=settings.OTEL_BSP_MAX_QUEUE_SIZE,
            )
        )
        trace.set_tracer_provider(provider)
        atexit.register(provider.shutdown)
        _initialized = True
        LOG.info("OSS OTEL tracer provider initialized")
        return True
    except Exception as exc:
        LOG.warning(
            "OSS OTEL initialization failed; tracing disabled",
            error_type=type(exc).__name__,
        )
        return False
