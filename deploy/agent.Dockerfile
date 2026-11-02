# agent-service with search-mcp and inventory-mcp in one environment: the agent starts them from its own bin directory.
FROM python:3.11.9-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY services/agent-service services/agent-service
COPY services/search-mcp services/search-mcp
COPY services/inventory-mcp services/inventory-mcp
COPY services/indexer services/indexer
RUN uv sync --frozen --no-dev --all-packages
RUN useradd --system app && mkdir .local && chown app .local
USER app
ENV PATH=/app/.venv/bin:$PATH
CMD ["agent-service"]
