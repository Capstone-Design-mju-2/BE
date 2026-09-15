from fastapi import FastAPI

from agent_service.config import settings

app = FastAPI(title="Capstone Agent Service", version="0.1.0")


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
