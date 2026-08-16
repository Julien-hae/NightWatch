# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations

RUN poetry install --only main --no-root \
    && poetry install --only main

# Run as an unprivileged, non-login user — a code-level compromise then runs as this
# user, not root. /app doesn't need to be writable at runtime (no local state is
# written outside of what asyncpg/nats-py hold in memory), but chown it anyway so
# read access never depends on the build environment's umask.
RUN groupadd --gid 1000 nightwatch \
    && useradd --uid 1000 --gid nightwatch --no-create-home --shell /usr/sbin/nologin nightwatch \
    && chown -R nightwatch:nightwatch /app

USER nightwatch

EXPOSE 8000

# curl is already installed above for this. Generous start-period: migrations run
# before /healthz can ever answer, and can take a few seconds against a cold Postgres.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["python", "-m", "Nightwatch.main"]
