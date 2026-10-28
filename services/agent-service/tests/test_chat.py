"""uv run --package agent-service python -m unittest discover -s services/agent-service/tests"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agent_service import agent
from agent_service.llm import LlmError
from agent_service.main import app, get_llm, get_tools
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

    definitions = []

    async def call(self, name, arguments):
        if name == "search_products":
            return await self.search_products(arguments["q"], arguments.get("max_price"), arguments.get("limit", 5))
        if name == "check_inventory":
            return await self.check_inventory(arguments["product_ids"])
        raise ToolError(f"{name} is not a tool")


class FakeLlm:
    """Plays back assistant messages in order; an exception in the script is raised instead."""

    timeout = 60.0

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    async def complete(self, messages, tools, timeout=None):
        self.requests.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, {"total_tokens": 100}


class SlowLlm(FakeLlm):
    """Each call takes `delay` seconds and, like Llm, gives up when the time it is handed runs out."""

    def __init__(self, delay, *replies):
        super().__init__(*replies)
        self.delay = delay

    async def complete(self, messages, tools, timeout=None):
        try:
            async with asyncio.timeout(timeout):
                await asyncio.sleep(self.delay)
        except TimeoutError as error:
            raise LlmError("timed out") from error
        return await super().complete(messages, tools, timeout)


def tool_call(name, arguments):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"call-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def final(answer, reasons):
    return {"role": "assistant", "content": json.dumps({"answer": answer, "reasons": reasons}, ensure_ascii=False)}


def serve(search=None, inventory=None, llm=None):
    tools = FakeTools(search, inventory)
    app.dependency_overrides[get_tools] = lambda: tools
    app.dependency_overrides[get_llm] = lambda: llm
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


class LlmChatTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.trace_dir = tempfile.TemporaryDirectory()
        self.original_trace_path = agent.TRACE_PATH
        agent.TRACE_PATH = Path(self.trace_dir.name) / "chat-trace.jsonl"

    def tearDown(self):
        app.dependency_overrides.clear()
        agent.TRACE_PATH = self.original_trace_path
        self.trace_dir.cleanup()

    def chat(self, message=MESSAGE):
        return self.client.post("/api/v1/chat", json={"message": message})

    def traces(self):
        return [json.loads(line) for line in agent.TRACE_PATH.read_text(encoding="utf-8").splitlines()]

    def test_LLM이_검색과_재고를_부르면_answer와_reason이_채워지고_NOT_FOUND는_빠진다(self):
        tools = serve(SEARCH, INVENTORY, FakeLlm(
            tool_call("search_products", {"q": "수분크림", "max_price": 30000, "limit": 20}),
            tool_call("check_inventory", {"product_ids": [1, 2, 3]}),
            final("촉촉한 수분크림 두 개를 골랐어요.", {"1": "촉촉하다는 리뷰가 있어요.", "2": "무난하다는 평이에요."})))
        body = self.chat().json()

        self.assertEqual(body["answer"], "촉촉한 수분크림 두 개를 골랐어요.")
        self.assertEqual([(p["productId"], p["reason"], p["inventory"]["status"]) for p in body["products"]],
                         [(1, "촉촉하다는 리뷰가 있어요.", "IN_STOCK"), (2, "무난하다는 평이에요.", "OUT_OF_STOCK")])
        self.assertEqual(tools.calls, [("search_products", "수분크림", 30000, 5), ("check_inventory", [1, 2, 3])])
        trace = self.traces()[-1]
        self.assertEqual(trace["reasons"]["1"]["evidence"], SEARCH["products"][0]["evidence"])
        self.assertNotIn("error", trace)

    def test_LLM이_재고를_안_부르면_재고는_전부_UNKNOWN이다(self):
        tools = serve(SEARCH, INVENTORY, FakeLlm(
            tool_call("search_products", {"q": "수분크림"}),
            final("세 개 찾았어요.", {})))
        body = self.chat().json()

        self.assertEqual({p["inventory"]["status"] for p in body["products"]}, {"UNKNOWN"})
        self.assertEqual([p["reason"] for p in body["products"]], [None, None, None])
        self.assertEqual([call[0] for call in tools.calls], ["search_products"])

    def test_검색_결과에_없는_상품의_reason은_버린다(self):
        serve(SEARCH, INVENTORY, FakeLlm(
            tool_call("search_products", {"q": "수분크림"}),
            tool_call("check_inventory", {"product_ids": [1, 2, 3]}),
            final("찾았어요.", {"1": "촉촉해요.", "99": "없는 상품"})))
        body = self.chat().json()

        self.assertEqual([p["productId"] for p in body["products"]], [1, 2])
        self.assertEqual([p["reason"] for p in body["products"]], ["촉촉해요.", None])
        self.assertFalse(self.traces()[-1]["reasons"]["99"]["inSearch"])

    def test_도구_이름에_붙은_채널_표시는_떼고_부른다(self):
        tools = serve(SEARCH, INVENTORY, FakeLlm(
            tool_call("search_products<|channel|>commentary", {"q": "수분크림"}),
            final("세 개 찾았어요.", {})))
        body = self.chat().json()

        self.assertEqual(len(body["products"]), 3)
        self.assertEqual([call[0] for call in tools.calls], ["search_products"])

    def test_도구_오류는_LLM에게_돌려주고_LLM이_이어서_답한다(self):
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                      tool_call("check_inventory", {"product_ids": [1, 2, 3]}),
                      final("재고는 확인하지 못했어요.", {}))
        serve(SEARCH, None, llm)
        body = self.chat().json()

        self.assertEqual({p["inventory"]["status"] for p in body["products"]}, {"UNKNOWN"})
        self.assertIn("error", json.loads(llm.requests[-1][-1]["content"]))

    def test_LLM이_실패하면_1B_규칙으로_답한다(self):
        for label, llm in (("API 오류", FakeLlm(LlmError("429"))),
                           ("JSON 아닌 답", FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                                                   {"role": "assistant", "content": "수분크림 추천해요"}))):
            with self.subTest(label):
                tools = serve(SEARCH, INVENTORY, llm)
                body = self.chat().json()

                self.assertEqual(body["answer"], "조건에 맞는 상품 2개를 찾았습니다.")
                self.assertTrue(all(p["reason"] is None for p in body["products"]))
                self.assertEqual(tools.calls[-2:], [("search_products", "수분크림", 30000, 5),
                                                    ("check_inventory", [1, 2, 3])])
                self.assertIn("error", self.traces()[-1])

    def test_LLM_시간_제한은_호출마다가_아니라_질문_하나_전체에_걸린다(self):
        # Each 0.2s call fits the 0.5s limit on its own; the third one does not fit what is left.
        llm = SlowLlm(0.2, tool_call("search_products", {"q": "수분크림"}),
                      tool_call("check_inventory", {"product_ids": [1, 2, 3]}),
                      final("찾았어요.", {}))
        llm.timeout = 0.5
        serve(SEARCH, INVENTORY, llm)
        body = self.chat().json()

        self.assertEqual(body["answer"], "조건에 맞는 상품 2개를 찾았습니다.")
        self.assertIn("error", self.traces()[-1])

    def test_LLM_경로에서_catalog가_내려가면_1B도_실패해_오류_본문을_반환한다(self):
        tools = serve(None, INVENTORY, FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                                                final("검색이 안 돼요.", {})))
        response = self.chat()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "PRODUCT_SEARCH_FAILED")
        self.assertEqual([call[0] for call in tools.calls], ["search_products", "search_products"])


if __name__ == "__main__":
    unittest.main()
