FROM python:3.13-slim AS builder

    RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

    COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

    ENV UV_LINK_MODE=copy

    WORKDIR /opt/coach
    COPY coach/pyproject.toml coach/README.md /opt/coach/
    COPY coach/app /opt/coach/app
    COPY coach/config /opt/coach/config
    RUN uv sync --no-dev

FROM python:3.13-slim

    COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

    COPY --from=builder /opt/coach /opt/coach

    RUN mkdir -p /data

    WORKDIR /opt/coach

    CMD ["uv", "run", "--no-sync", "--directory", "/opt/coach", "start"]
