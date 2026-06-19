"""Tracing via OpenInference + OpenTelemetry.

Spans are always kept in process (for tests/inspection) and additionally exported to
Phoenix (OTLP gRPC, keyless) and Langfuse (OTLP HTTP, needs keys from the Langfuse UI)
when those are enabled. The instrumentation is the same everywhere; only the sinks differ.
"""
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
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

    if settings.phoenix_enabled and settings.phoenix_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.phoenix_otlp_endpoint, insecure=True))
            )
        except Exception:
            pass

    if settings.langfuse_enabled and settings.langfuse_public_key and settings.langfuse_secret_key:
        try:
            import base64

            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter

            auth = base64.b64encode(
                f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
            ).decode()
            provider.add_span_processor(
                BatchSpanProcessor(
                    HTTPExporter(
                        endpoint=f"{settings.langfuse_host}/api/public/otel/v1/traces",
                        headers={"Authorization": f"Basic {auth}"},
                    )
                )
            )
        except Exception:
            pass

    LangChainInstrumentor().instrument(tracer_provider=provider)
    _started = True
    return _exporter


def span_names() -> list[str]:
    return [s.name for s in _exporter.get_finished_spans()]
