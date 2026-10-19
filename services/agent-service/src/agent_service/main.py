import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent_service.agent import SEARCH_LIMIT, cards, inventory_by_id, run_agent
from agent_service.config import settings
from agent_service.extract import extract
from agent_service.llm import Llm, LlmError
from agent_service.tools import McpTools, ToolError

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 500
NOT_FOUND_ANSWER = "조건에 맞는 상품을 찾지 못했습니다."


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with McpTools() as tools:
        app.state.tools = tools
        yield


app = FastAPI(title="Capstone Agent Service", version="0.1.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400,
                        content={"code": "INVALID_CHAT_REQUEST",
                                 "message": f"message는 1자 이상 {MAX_MESSAGE_LENGTH}자 이하여야 합니다."})


def get_tools(request: Request) -> McpTools:
    return request.app.state.tools


def get_llm() -> Llm | None:
    if not settings.llm_api_key:
        return None
    return Llm(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout_seconds)


@app.post("/api/v1/chat", tags=["chat"])
async def chat(request: ChatRequest, tools: McpTools = Depends(get_tools), llm: Llm | None = Depends(get_llm)):
    try:
        if llm is not None:
            try:
                answer, products, inventories, reasons = await run_agent(request.message, llm, tools)
                return {"answer": answer, "products": cards(products, inventories, reasons)}
            except LlmError as error:
                logger.warning("LLM could not answer, falling back to the 1B rules (ADR-92): %r", error)
        return await _rule_chat(request.message, tools)
    except ToolError:
        return JSONResponse(status_code=502,
                            content={"code": "PRODUCT_SEARCH_FAILED", "message": "상품 검색에 실패했습니다."})


async def _rule_chat(message: str, tools: McpTools) -> dict:
    """Stage 1B: rule-based arguments, fixed tool order, template answer, no reason."""
    q, max_price = extract(message)
    if q is None:
        return {"answer": NOT_FOUND_ANSWER, "products": []}

    products = (await tools.search_products(q, max_price, SEARCH_LIMIT))["products"]
    inventories = await _check_inventories(tools, [p["productId"] for p in products])
    found = cards(products, inventories, {})
    answer = f"조건에 맞는 상품 {len(found)}개를 찾았습니다." if found else NOT_FOUND_ANSWER
    return {"answer": answer, "products": found}


async def _check_inventories(tools: McpTools, product_ids: list[int]) -> dict[int, dict]:
    """Missing entries mean UNKNOWN: an order failure must not look like sold out."""
    if not product_ids:
        return {}
    try:
        checked = await tools.check_inventory(product_ids)
    except ToolError:
        return {}
    return inventory_by_id(checked)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {
        "status": "UP",
        "service": "agent-service",
    }


@app.get("/config", tags=["system"])
async def config() -> dict[str, str]:
    return {
        "catalogServiceUrl": settings.catalog_service_url,
        "orderServiceUrl": settings.order_service_url,
    }
