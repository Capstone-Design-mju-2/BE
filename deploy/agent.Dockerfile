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
# --all-extras brings search-mcp's BGE-M3 for SEARCH_BACKEND=opensearch (ADR-130). The uv cache stays out of the image.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --all-packages --all-extras
RUN useradd --system app && mkdir .local .hf && chown app .local .hf
USER app
ENV PATH=/app/.venv/bin:$PATH HF_HOME=/app/.hf
# The model (2.3 GB) is fetched here so a start never waits for the download; starts then read it offline. Only the
# main branch's pytorch_model.bin: loading by name also fetched a safetensors conversion, a second 2.3 GB copy.
ENV HF_HUB_OFFLINE=1
RUN HF_HUB_OFFLINE=0 python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', \
        allow_patterns=['*.json', 'pytorch_model.bin', 'sentencepiece.bpe.model'])" \
    && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
CMD ["agent-service"]
