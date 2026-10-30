import asyncio
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from index_reviews import mapping, request

ROOT_DIR = Path(__file__).resolve().parents[1]
FIXTURES = ROOT_DIR / "scripts/fixtures"
SMOKE_INDEX = "reviews-smoke"
CATALOG_URL = "http://{}:{}".format(os.getenv("CATALOG_SERVICE_HOST", "127.0.0.1"),
                                    os.getenv("CATALOG_SERVICE_PORT", "8081"))
ORDER_URL = "http://{}:{}".format(os.getenv("ORDER_SERVICE_HOST", "127.0.0.1"),
                                  os.getenv("ORDER_SERVICE_PORT", "8082"))
AGENT_URL = "http://{}:{}".format(os.getenv("AGENT_SERVICE_HOST", "127.0.0.1"),
                                  os.getenv("AGENT_SERVICE_PORT", "8000"))


async def check_server(package: str, executable: str, expected_service: str, env: dict[str, str],
                       tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    parameters = StdioServerParameters(
        command="uv",
        args=["run", "--package", package, executable],
        cwd=ROOT_DIR,
        env=env,
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            if "health" not in tool_names or tool_name not in tool_names:
                raise RuntimeError(f"{package} does not expose health and {tool_name}: {tool_names}")

            result = await session.call_tool("health", {})
            expected = {"status": "UP", "service": expected_service}
            if result.structured_content != expected:
                raise RuntimeError(
                    f"{package} returned unexpected health content: "
                    f"{result.structured_content!r}"
                )
            print(f"{package} MCP health is UP")

            result = await session.call_tool(tool_name, arguments)
            if result.is_error or result.structured_content is None:
                raise RuntimeError(f"{package} {tool_name} failed: {result.content!r}")
            return result.structured_content


def check_chat() -> None:
    request = urllib.request.Request(f"{AGENT_URL}/api/v1/chat",
                                     data=json.dumps({"message": "토너 추천해줘"}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    if response.status != 200 or not isinstance(body.get("products"), list) or "answer" not in body:
        raise RuntimeError(f"agent /chat through the MCP tools returned an unexpected answer: {body!r}")
    print(f"agent /chat through the MCP tools answered: {body['answer']}")


async def check_semantic_search() -> None:
    """Index the fixture reviews with the real mapping and search them through search-mcp's OpenSearch path."""
    request("DELETE", f"/{SMOKE_INDEX}?ignore_unavailable=true")
    request("PUT", f"/{SMOKE_INDEX}", mapping("2x"))
    lines = []
    for review in json.loads((FIXTURES / "search-reviews.json").read_text(encoding="utf-8")):
        lines += [json.dumps({"index": {"_index": SMOKE_INDEX, "_id": review["review_id"]}}),
                  json.dumps(review, ensure_ascii=False)]
    if request("POST", "/_bulk?refresh=true", "\n".join(lines) + "\n")["errors"]:
        raise RuntimeError("indexing the semantic search fixture failed")

    env = {"SEARCH_BACKEND": "opensearch", "OPENSEARCH_URL": os.getenv("OPENSEARCH_URL", "http://127.0.0.1:9200"),
           "OPENSEARCH_INDEX": SMOKE_INDEX, "QUERY_VECTORS": str(FIXTURES / "search-queries.json")}
    found = await check_server("search-mcp", "search-mcp", "search-mcp", env,
                               "search_products", {"q": "건성 피부에 촉촉한 수분크림"})
    if [p["productId"] for p in found["products"]][:1] != [1001]:
        raise RuntimeError(f"semantic search did not rank the moisturiser first: {found!r}")
    found = await check_server("search-mcp", "search-mcp", "search-mcp", env,
                               "search_products", {"q": "예민한 피부를 진정시키는 토너", "max_price": 30000})
    if not found["products"] or any(p["price"] > 30000 for p in found["products"]):
        raise RuntimeError(f"semantic search ignored max_price: {found!r}")
    found = await check_server("search-mcp", "search-mcp", "search-mcp", env,
                               "search_products", {"q": "건성 피부에 촉촉한 수분크림", "exclude_ingredients": ["향료"]})
    if [p["productId"] for p in found["products"]] != [1001]:
        raise RuntimeError(f"semantic search kept a product with 향료 or without an ingredient list: {found!r}")
    print("search_products over OpenSearch ranked by meaning, kept max_price and excluded ingredients")


async def main() -> None:
    found = await check_server("search-mcp", "search-mcp", "search-mcp", {"CATALOG_SERVICE_URL": CATALOG_URL},
                               "search_products", {"q": "토너", "limit": 1})
    if not isinstance(found.get("products"), list):
        raise RuntimeError(f"search_products returned an unexpected result: {found!r}")
    print(f"search_products answered with {len(found['products'])} product(s)")

    await check_semantic_search()

    checked = await check_server("inventory-mcp", "inventory-mcp", "inventory-mcp",
                                 {"ORDER_SERVICE_URL": ORDER_URL},
                                 "check_inventory", {"product_ids": [999999999]})
    if [(i["productId"], i["status"]) for i in checked["inventories"]] != [(999999999, "NOT_FOUND")]:
        raise RuntimeError(f"check_inventory returned an unexpected result: {checked!r}")
    print("check_inventory answered NOT_FOUND for an unknown product id")

    check_chat()


if __name__ == "__main__":
    asyncio.run(main())
