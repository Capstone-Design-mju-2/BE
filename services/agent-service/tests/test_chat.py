"""uv run --package agent-service python -m unittest discover -s services/agent-service/tests"""

import unittest

from fastapi.testclient import TestClient

from agent_service.main import app, get_tools
from agent_service.tools import ToolError

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


class FakeTools:
    """search/inventory: tool result dict, or None for a failed tool call."""

    def __init__(self, search, inventory):
        self.search, self.inventory = search, inventory
        self.calls = []

    async def search_products(self, q, max_price, limit):
        self.calls.append(("search_products", q, max_price, limit))
        if self.search is None:
            raise ToolError("search_products could not be called")
        return self.search

    async def check_inventory(self, product_ids):
        self.calls.append(("check_inventory", product_ids))
        if self.inventory is None:
            raise ToolError("check_inventory could not be called")
        return self.inventory


def serve(search=None, inventory=None):
    tools = FakeTools(search, inventory)
    app.dependency_overrides[get_tools] = lambda: tools
    return tools


class ChatTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def chat(self, message=MESSAGE):
        return self.client.post("/api/v1/chat", json={"message": message})

    def test_정상일_때_카드에_evidence와_inventory가_채워지고_NOT_FOUND는_빠진다(self):
        tools = serve(SEARCH, INVENTORY)
        body = self.chat().json()

        self.assertEqual(body["answer"], "조건에 맞는 상품 2개를 찾았습니다.")
        self.assertEqual([p["productId"] for p in body["products"]], [1, 2])
        self.assertEqual(body["products"][0]["inventory"]["status"], "IN_STOCK")
        self.assertEqual(body["products"][1]["inventory"]["status"], "OUT_OF_STOCK")
        self.assertTrue(all(p["evidence"] and p["reason"] is None for p in body["products"]))
        self.assertEqual(tools.calls, [("search_products", "수분크림", 30000, 5),
                                       ("check_inventory", [1, 2, 3])])

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
        tools = serve(SEARCH, INVENTORY)
        body = self.chat("안녕하세요").json()

        self.assertEqual(body, {"answer": "조건에 맞는 상품을 찾지 못했습니다.", "products": []})
        self.assertEqual(tools.calls, [])

    def test_message가_없거나_비었거나_너무_길면_400과_오류_본문을_반환한다(self):
        serve(SEARCH, INVENTORY)

        for label, payload in (("없음", {}), ("빈 문자열", {"message": ""}), ("501자", {"message": "가" * 501})):
            with self.subTest(label):
                response = self.client.post("/api/v1/chat", json=payload)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "INVALID_CHAT_REQUEST")

    def test_message가_500자면_받아들인다(self):
        serve(SEARCH, INVENTORY)

        self.assertEqual(self.chat("토너 " + "가" * 497).status_code, 200)

    def test_범위를_벗어난_가격은_가격_조건_없이_검색한다(self):
        tools = serve(SEARCH, INVENTORY)

        self.assertEqual(self.chat("토너 99999999999원 이하").status_code, 200)
        self.assertEqual(tools.calls[0], ("search_products", "토너", None, 5))


if __name__ == "__main__":
    unittest.main()
