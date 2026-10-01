from collections.abc import AsyncIterator

import httpx
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent_service.config import settings
from agent_service.extract import extract

SEARCH_LIMIT = 5
NOT_FOUND_ANSWER = "조건에 맞는 상품을 찾지 못했습니다."
UNKNOWN_INVENTORY = {"status": "UNKNOWN", "quantity": None, "estimatedDeliveryDate": None}

app = FastAPI(title="Capstone Agent Service", version="0.1.0")


class ChatRequest(BaseModel):
    message: str


async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=3.0) as client:
        yield client


@app.post("/api/v1/chat", tags=["chat"])
async def chat(request: ChatRequest, client: httpx.AsyncClient = Depends(http_client)):
    q, max_price = extract(request.message)
    if q is None:
        return {"answer": NOT_FOUND_ANSWER, "products": []}

    params = {"q": q, "limit": SEARCH_LIMIT}
    if max_price is not None:
        params["maxPrice"] = max_price
    try:
        response = await client.get(f"{settings.catalog_service_url}/api/v1/products/search", params=params)
        response.raise_for_status()
    except httpx.HTTPError:
        return JSONResponse(status_code=502,
                            content={"code": "PRODUCT_SEARCH_FAILED", "message": "상품 검색에 실패했습니다."})
    products = response.json()["products"]

    inventories = await _check_inventories(client, [p["productId"] for p in products])
    cards = [
        {**p, "reason": None, "inventory": inventories.get(p["productId"], UNKNOWN_INVENTORY)}
        for p in products
        if inventories.get(p["productId"], UNKNOWN_INVENTORY)["status"] != "NOT_FOUND"
    ]
    answer = f"조건에 맞는 상품 {len(cards)}개를 찾았습니다." if cards else NOT_FOUND_ANSWER
    return {"answer": answer, "products": cards}


async def _check_inventories(client: httpx.AsyncClient, product_ids: list[int]) -> dict[int, dict]:
    """Missing entries mean UNKNOWN: an order failure must not look like sold out."""
    if not product_ids:
        return {}
    try:
        response = await client.post(f"{settings.order_service_url}/api/v1/inventories/check",
                                     json={"productIds": product_ids})
        response.raise_for_status()
    except httpx.HTTPError:
        return {}
    return {
        item["productId"]: {k: item[k] for k in ("status", "quantity", "estimatedDeliveryDate")}
        for item in response.json()["inventories"]
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
