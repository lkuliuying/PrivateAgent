# syntax=docker/dockerfile:1.7

# Keep the build tool and runtime aligned with the versions verified in this
# repository.  The application dependency graph itself is locked by uv.lock.
FROM ghcr.io/astral-sh/uv:0.11.26 AS uv
FROM python:3.13.13-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_CONCURRENT_DOWNLOADS=4 \
    UV_HTTP_CONNECT_TIMEOUT=30 \
    UV_HTTP_RETRIES=5 \
    UV_HTTP_TIMEOUT=300 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-editable

FROM python:3.13.13-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="PrivateAgent API" \
      org.opencontainers.image.version="0.1.2" \
      org.opencontainers.image.description="Optional authenticated PrivateAgent backend deployment"

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PA_API_HOST=127.0.0.1 \
    PA_API_PORT=8000 \
    PA_API_AUTH_ENABLED=true \
    PA_API_ALLOW_NON_LOOPBACK_BIND=false \
    PA_DATA_DIR=/app/data

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 -o Acquire::https::Timeout=120 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::https::Timeout=120 install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 privateagent \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/privateagent privateagent \
    && mkdir -p /app/data \
    && chown -R 10001:10001 /app/data /home/privateagent

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM

# The token is read from a mounted secret (preferred) or process environment at
# probe time; it is not expanded into image metadata or the healthcheck command.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import os,pathlib,urllib.request; token=os.environ.get('PA_API_TOKEN') or pathlib.Path(os.environ['PA_API_TOKEN_FILE']).read_text(encoding='utf-8').strip(); request=urllib.request.Request('http://127.0.0.1:8000/',headers={'Authorization':'Bearer '+token}); response=urllib.request.urlopen(request,timeout=4); status=response.status; response.close(); assert status == 200"]

CMD ["python", "-m", "personal_assistant.server_entry"]
