FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.24 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/.venv

WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

RUN uv sync --frozen --no-dev \
    && chmod +x /srv/scripts/start.sh


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/srv/.venv/bin:$PATH"

WORKDIR /srv

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

COPY --from=builder --chown=appuser:appuser /srv/.venv /srv/.venv
COPY --from=builder --chown=appuser:appuser /srv/alembic.ini /srv/alembic.ini
COPY --from=builder --chown=appuser:appuser /srv/alembic /srv/alembic
COPY --from=builder --chown=appuser:appuser /srv/app /srv/app
COPY --from=builder --chown=appuser:appuser /srv/scripts /srv/scripts

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

CMD ["sh", "scripts/start.sh"]
