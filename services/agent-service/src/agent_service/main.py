import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent_service.agent import cards, inventory_by_id, run_agent, search
from agent_service.config import settings
from agent_service.extract import extract
from agent_service.llm import Llm, LlmError
from agent_service.tools import McpTools, ToolError

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 500
# Each excluded product makes the search ask for one more, and the search tool takes at most 20 (ADR-131).
MAX_EXCLUDED = 10
NOT_FOUND_ANSWER = "조건에 맞는 상품을 찾지 못했습니다."


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with McpTools() as tools:
        app.state.tools = tools
        yield


app = FastAPI(title="Capstone Agent Service", version="0.1.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    skin_type: Literal["dry", "oily", "combination", "sensitive"] | None = Field(default=None, alias="skinType")
    # An alternative to a sold-out product (ADR-131). The screen sends back the conditions it was given, and the search
    # tool checks their values, so here they only have to be an object.
    search_conditions: dict[str, Any] | None = Field(default=None, alias="searchConditions")
    exclude_product_ids: list[int] = Field(default_factory=list, alias="excludeProductIds", max_length=MAX_EXCLUDED)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400,
                        content={"code": "INVALID_CHAT_REQUEST",
                                 "message": f"message는 1자 이상 {MAX_MESSAGE_LENGTH}자 이하, "
                                            "skinType은 dry·oily·combination·sensitive, searchConditions는 객체, "
                                            f"excludeProductIds는 숫자 {MAX_EXCLUDED}개 이하여야 합니다."})


def get_tools(request: Request) -> McpTools:
    return request.app.state.tools


def get_llm() -> Llm | None:
    if not settings.llm_api_key:
        return None
    call_timeout = settings.llm_fallback_after_seconds if get_fallback_llm() else None
    return Llm(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout_seconds,
               call_timeout)


def get_fallback_llm() -> Llm | None:
    if not (settings.llm_fallback_model and settings.llm_fallback_api_key):
        return None
    return Llm(settings.llm_fallback_base_url, settings.llm_fallback_api_key, settings.llm_fallback_model,
               settings.llm_timeout_seconds)


@app.post("/api/v1/chat", tags=["chat"])
async def chat(request: ChatRequest, tools: McpTools = Depends(get_tools), llm: Llm | None = Depends(get_llm),
               fallback: Llm | None = Depends(get_fallback_llm)):
    try:
        if llm is not None:
            # Both LLMs share one limit, so the screen still has one wait to plan for (ADR-129).
            deadline = time.monotonic() + llm.timeout
            for current in [llm, fallback] if fallback else [llm]:
                try:
                    answer, products, inventories, reasons, searched = await run_agent(
                        request.message, current, tools, request.skin_type, deadline,
                        request.search_conditions, request.exclude_product_ids)
                    return {"answer": answer, "products": cards(products, inventories, reasons),
                            "searchConditions": searched}
                except LlmError as error:
                    logger.warning("LLM %s could not answer (ADR-92, ADR-129): %r", current.model, error)
                    if not error.provider_down:
                        break
        return await _rule_chat(request.message, tools, request.skin_type, request.search_conditions,
                                request.exclude_product_ids)
    except ToolError:
        return JSONResponse(status_code=502,
                            content={"code": "PRODUCT_SEARCH_FAILED", "message": "상품 검색에 실패했습니다."})


async def _rule_chat(message: str, tools: McpTools, skin_type: str | None, conditions: dict[str, Any] | None,
                     exclude: list[int]) -> dict:
    """Stage 1B: rule-based arguments, fixed tool order, template answer, no reason.

    An alternative to a sold-out product searches the first answer's conditions instead of the rules' (ADR-131).
    """
    if conditions is None:
        q, max_price = extract(message)
        if q is None:
            return {"answer": NOT_FOUND_ANSWER, "products": [], "searchConditions": None}
        conditions = {"q": q, "max_price": max_price}

    products = (await search(tools, conditions, skin_type, exclude))["products"]
    inventories = await _check_inventories(tools, [p["productId"] for p in products])
    found = cards(products, inventories, {})
    answer = f"조건에 맞는 상품 {len(found)}개를 찾았습니다." if found else NOT_FOUND_ANSWER
    return {"answer": answer, "products": found, "searchConditions": conditions}


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
