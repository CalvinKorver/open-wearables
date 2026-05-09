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

    WORKDIR /opt/mcp
    COPY mcp/pyproject.toml mcp/uv.lock mcp/README.md /opt/mcp/
    COPY mcp/app /opt/mcp/app
    COPY mcp/config /opt/mcp/config
    RUN uv sync --no-dev --frozen

FROM python:3.13-slim

    COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

    COPY --from=builder /opt/coach /opt/coach
    COPY --from=builder /opt/mcp /opt/mcp

    RUN mkdir -p /data
    VOLUME /data

    WORKDIR /opt/coach

    CMD ["uv", "run", "--no-sync", "--directory", "/opt/coach", "start"]
