"""uv run --package agent-service python -m unittest discover -s services/agent-service/tests"""

import json
import unittest

import httpx
from fastapi.testclient import TestClient

from agent_service.main import app, http_client

MESSAGE = "건성 피부에 끈적이지 않는 수분크림 중 3만원 이하인 상품 추천해 줘"
SEARCH = {"products": [
    {"productId": 1, "name": "크림 A", "brand": "A", "price": 25000,
     "evidence": [{"reviewId": 11, "rating": 5, "excerpt": "수분크림으로 촉촉해요"}]},
    {"productId": 2, "name": "크림 B", "brand": "B", "price": 19000,
     "evidence": [{"reviewId": 21, "rating": 4, "excerpt": "수분크림 무난해요"}]},
    {"productId": 3, "name": "크림 C", "brand": "C", "price": 9000,
     "evidence": [{"reviewId": 31, "rating": 5, "excerpt": "수분크림 가성비"}]},
]}
INVENTORY = {"inventories": [
    {"productId": 1, "status": "IN_STOCK", "quantity": 12, "estimatedDeliveryDate": "2026-10-02"},
    {"productId": 2, "status": "OUT_OF_STOCK", "quantity": 0, "estimatedDeliveryDate": None},
    {"productId": 3, "status": "NOT_FOUND", "quantity": None, "estimatedDeliveryDate": None},
]}


def serve(catalog=None, order=None):
    """catalog/order: response body dict, or None for a connection failure."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = catalog if request.url.path.endswith("/search") else order
        if body is None:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json=body)

    async def override():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            yield client

    app.dependency_overrides[http_client] = override
    return seen


class ChatTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def chat(self, message=MESSAGE):
        return self.client.post("/api/v1/chat", json={"message": message})

    def test_정상일_때_카드에_evidence와_inventory가_채워지고_NOT_FOUND는_빠진다(self):
        seen = serve(SEARCH, INVENTORY)
        body = self.chat().json()

        self.assertEqual(body["answer"], "조건에 맞는 상품 2개를 찾았습니다.")
        self.assertEqual([p["productId"] for p in body["products"]], [1, 2])
        self.assertEqual(body["products"][0]["inventory"]["status"], "IN_STOCK")
        self.assertEqual(body["products"][1]["inventory"]["status"], "OUT_OF_STOCK")
        self.assertTrue(all(p["evidence"] and p["reason"] is None for p in body["products"]))
        self.assertEqual(dict(seen[0].url.params), {"q": "수분크림", "limit": "5", "maxPrice": "30000"})
        self.assertEqual(json.loads(seen[1].content), {"productIds": [1, 2, 3]})

    def test_order가_내려가면_카드는_그대로이고_재고는_전부_UNKNOWN이다(self):
        serve(SEARCH, None)
        body = self.chat().json()

        self.assertEqual(len(body["products"]), 3)
        self.assertEqual({p["inventory"]["status"] for p in body["products"]}, {"UNKNOWN"})

    def test_catalog가_내려가면_오류_본문을_반환한다(self):
        serve(None, INVENTORY)
        response = self.chat()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "PRODUCT_SEARCH_FAILED")

    def test_사전_단어가_없으면_검색하지_않고_0개를_반환한다(self):
        seen = serve(SEARCH, INVENTORY)
        body = self.chat("안녕하세요").json()

        self.assertEqual(body, {"answer": "조건에 맞는 상품을 찾지 못했습니다.", "products": []})
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
