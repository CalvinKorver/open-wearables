FROM python:3.13-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy

WORKDIR /opt/mcp
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY config ./config
RUN uv sync --frozen --no-dev

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY --from=builder /opt/mcp /opt/mcp

WORKDIR /opt/mcp

EXPOSE 8765

CMD ["uv", "run", "--no-sync", "--directory", "/opt/mcp", "start-http"]
