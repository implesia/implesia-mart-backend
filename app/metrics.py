"""In-process HTTP counters. No external metrics service.

Gunicorn workers add to the same totals when PROMETHEUS_MULTIPROC_DIR is set.
Health probes and this scrape are left out so they do not hide API latency.
"""

import os

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

SKIP_PATHS = frozenset({"/metrics", "/health/live", "/health/ready"})

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP responses, excluding health probes and the metrics scrape.",
)
HTTP_5XX = Counter(
    "http_responses_5xx_total",
    "HTTP responses with status 500 or higher.",
)
HTTP_401 = Counter(
    "http_responses_401_total",
    "HTTP 401 responses.",
)
HTTP_429 = Counter(
    "http_responses_429_total",
    "HTTP 429 responses.",
)
LOGIN_FAILURES = Counter(
    "login_failures_total",
    "Failed login attempts.",
)
ADMIN_LOGIN_FAILURES = Counter(
    "admin_login_failures_total",
    "Failed logins for the admin email or a superadmin.",
)
LOGIN_ALERTS = Counter(
    "failed_login_alerts_total",
    "Times a failed-login window crossed its alert threshold.",
    labelnames=("kind",),
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds, excluding probes.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)


def observe_request(path: str, status: int, duration_seconds: float) -> None:
    if path in SKIP_PATHS:
        return
    HTTP_REQUESTS.inc()
    HTTP_LATENCY.observe(max(duration_seconds, 0.0))
    if status >= 500:
        HTTP_5XX.inc()
    elif status == 401:
        HTTP_401.inc()
    elif status == 429:
        HTTP_429.inc()


def render_http_metrics() -> bytes:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest()


__all__ = ["CONTENT_TYPE_LATEST", "observe_request", "render_http_metrics"]
