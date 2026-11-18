import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://localhost:8082")

server = MCPServer(
    name="inventory-mcp",
    instructions=(
        "Check real-time stock and delivery date for product ids. "
        "Every requested id is answered with IN_STOCK, OUT_OF_STOCK or NOT_FOUND."
    ),
)


@server.tool()
def health() -> dict[str, str]:
    """Return the MCP server health status."""
    return {
        "status": "UP",
        "service": "inventory-mcp",
    }


@server.tool()
async def check_inventory(product_ids: list[int]) -> dict[str, Any]:
    """Check stock for up to 20 product ids and return one entry per requested id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{ORDER_SERVICE_URL}/api/v1/inventories/check",
                                     json={"productIds": product_ids})
        response.raise_for_status()
        return response.json()


def export_traces() -> None:
    """Send spans to OTEL_EXPORTER_OTLP_ENDPOINT under OTEL_SERVICE_NAME; left unset, tracing does nothing (ADR-182)."""
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()


def main() -> None:
    export_traces()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
