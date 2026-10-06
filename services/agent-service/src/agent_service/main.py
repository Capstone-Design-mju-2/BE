from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent_service.config import settings
from agent_service.extract import extract
from agent_service.tools import McpTools, ToolError

SEARCH_LIMIT = 5
NOT_FOUND_ANSWER = "조건에 맞는 상품을 찾지 못했습니다."
UNKNOWN_INVENTORY = {"status": "UNKNOWN", "quantity": None, "estimatedDeliveryDate": None}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with McpTools() as tools:
        app.state.tools = tools
        yield


app = FastAPI(title="Capstone Agent Service", version="0.1.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str


def get_tools(request: Request) -> McpTools:
    return request.app.state.tools


@app.post("/api/v1/chat", tags=["chat"])
async def chat(request: ChatRequest, tools: McpTools = Depends(get_tools)):
    q, max_price = extract(request.message)
    if q is None:
        return {"answer": NOT_FOUND_ANSWER, "products": []}

    try:
        found = await tools.search_products(q, max_price, SEARCH_LIMIT)
    except ToolError:
        return JSONResponse(status_code=502,
                            content={"code": "PRODUCT_SEARCH_FAILED", "message": "상품 검색에 실패했습니다."})
    products = found["products"]

    inventories = await _check_inventories(tools, [p["productId"] for p in products])
    cards = [
        {**p, "reason": None, "inventory": inventories.get(p["productId"], UNKNOWN_INVENTORY)}
        for p in products
        if inventories.get(p["productId"], UNKNOWN_INVENTORY)["status"] != "NOT_FOUND"
    ]
    answer = f"조건에 맞는 상품 {len(cards)}개를 찾았습니다." if cards else NOT_FOUND_ANSWER
    return {"answer": answer, "products": cards}


async def _check_inventories(tools: McpTools, product_ids: list[int]) -> dict[int, dict]:
    """Missing entries mean UNKNOWN: an order failure must not look like sold out."""
    if not product_ids:
        return {}
    try:
        checked = await tools.check_inventory(product_ids)
    except ToolError:
        return {}
    return {
        item["productId"]: {k: item[k] for k in ("status", "quantity", "estimatedDeliveryDate")}
        for item in checked["inventories"]
    }


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
