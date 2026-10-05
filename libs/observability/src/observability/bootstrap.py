"""``bootstrap(...)``: wires logs + traces + metrics once at startup; idempotent."""

from __future__ import annotations

from .logging import setup_logging
from .metrics import setup_metrics
from .tracing import setup_tracing


def bootstrap(
    service_name: str,
    *,
    otlp_endpoint: str = "http://localhost:4317",
    log_level: str = "INFO",
    deployment_environment: str = "development",
    package_name: str | None = None,
    disable_otel: bool = False,
    prometheus_port: int | None = None,
) -> None:
    """Configure logs / traces / metrics; ``disable_otel`` skips tracing + metrics (tests)."""
    setup_logging(service_name, log_level)
    if disable_otel:
        return
    setup_tracing(
        service_name,
        otlp_endpoint,
        deployment_environment=deployment_environment,
        package_name=package_name,
    )
    setup_metrics(
        service_name,
        otlp_endpoint,
        prometheus_port=prometheus_port,
    )
