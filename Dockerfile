FROM python:3.13-slim-bookworm AS build

RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlite3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra api --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev --extra api

FROM python:3.13-slim-bookworm

RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/data
VOLUME /app/data

COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/pyproject.toml ./
COPY --from=build /app/src/ src/

ENV PATH="/app/.venv/bin:$PATH" \
    TERM=xterm-256color \
    COLORTERM=truecolor \
    PYTHONUNBUFFERED=1

COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["tui"]
