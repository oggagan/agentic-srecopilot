"""Tracing setup using OpenInference + OpenTelemetry.

For the POC we collect spans in process so we can prove every agent step is traced.
At the MVP we swap the in memory exporter for an OTLP exporter pointed at Phoenix and
Langfuse (both run in Docker then). The instrumentation here does not change.
"""
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.config import settings

_exporter = InMemorySpanExporter()
_started = False


def setup_tracing() -> InMemorySpanExporter:
    """Instrument LangChain once. Returns the in memory exporter for inspection."""
    global _started
    if _started or not settings.otel_enabled:
        return _exporter
    from openinference.instrumentation.langchain import LangChainInstrumentor

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_exporter))
    LangChainInstrumentor().instrument(tracer_provider=provider)
    _started = True
    return _exporter


def span_names() -> list[str]:
    return [s.name for s in _exporter.get_finished_spans()]
