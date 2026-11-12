"""uv run --package agent-service python -m unittest discover -s services/agent-service/tests"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agent_service import agent
from agent_service.llm import LlmError
from agent_service.main import app, get_fallback_llm, get_llm, get_tools
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
        self.skin_types = []
        self.searched = []
        self.reviews = {}

    async def search_products(self, q, max_price, limit, skin_type=None):
        self.calls.append(("search_products", q, max_price, limit))
        self.skin_types.append(skin_type)
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
            self.searched.append(arguments)
            return await self.search_products(arguments["q"], arguments.get("max_price"), arguments.get("limit", 5),
                                              arguments.get("skin_type"))
        if name == "check_inventory":
            return await self.check_inventory(arguments["product_ids"])
        if name == "search_product_reviews":
            self.calls.append((name, arguments["product_id"], arguments["q"]))
            return {"productId": arguments["product_id"], "reviews": self.reviews.get(arguments["product_id"], [])}
        raise ToolError(f"{name} is not a tool")


class FakeLlm:
    """Plays back assistant messages in order; an exception in the script is raised instead."""

    timeout = 60.0

    def __init__(self, *replies, model="fake"):
        self.model = model
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
            raise LlmError("timed out", provider_down=True) from error
        return await super().complete(messages, tools, timeout)


def tool_call(name, arguments):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"call-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def final(answer, reasons):
    return {"role": "assistant", "content": json.dumps({"answer": answer, "reasons": reasons}, ensure_ascii=False)}


def serve(search=None, inventory=None, llm=None, fallback=None):
    tools = FakeTools(search, inventory)
    app.dependency_overrides[get_tools] = lambda: tools
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_fallback_llm] = lambda: fallback
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

        self.assertEqual(body, {"answer": "조건에 맞는 상품을 찾지 못했습니다.", "products": [], "searchConditions": None})
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

    def test_skinType을_검색에_넘기고_null은_없는_것으로_본다(self):
        tools = serve(SEARCH, INVENTORY)

        for skin_type in ("dry", None):
            response = self.client.post("/api/v1/chat", json={"message": MESSAGE, "skinType": skin_type})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(tools.skin_types, ["dry", None])

    def test_skinType이_네_값_밖이면_400과_오류_본문을_반환한다(self):
        tools = serve(SEARCH, INVENTORY)

        for value in ("normal", "DRY", ""):
            with self.subTest(value):
                response = self.client.post("/api/v1/chat", json={"message": MESSAGE, "skinType": value})

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "INVALID_CHAT_REQUEST")
        self.assertEqual(tools.calls, [])

    def test_규칙_답에는_뽑은_검색_조건이_실린다(self):
        serve(SEARCH, INVENTORY)

        self.assertEqual(self.chat().json()["searchConditions"], {"q": "수분크림", "max_price": 30000})

    def test_대안은_보낸_검색_조건으로_찾고_뺀_상품_대신_더_찾아_5개를_채운다(self):
        six = {"products": [{**SEARCH["products"][0], "productId": i} for i in range(1, 7)]}
        tools = serve(six, None)
        conditions = {"q": "크림", "max_price": 20000, "category": "스킨케어"}
        body = self.client.post("/api/v1/chat", json={"message": "아무 말", "searchConditions": conditions,
                                                      "excludeProductIds": [1]}).json()

        self.assertEqual([p["productId"] for p in body["products"]], [2, 3, 4, 5, 6])
        self.assertEqual(tools.searched, [{**conditions, "limit": 6}])
        self.assertEqual(body["searchConditions"], conditions)

    def test_대안_필드의_형식이_틀리면_400과_오류_본문을_반환한다(self):
        tools = serve(SEARCH, INVENTORY)

        for label, fields in (("뺄 상품 11개", {"excludeProductIds": list(range(11))}),
                              ("숫자가 아닌 상품 ID", {"excludeProductIds": ["하나"]}),
                              ("객체가 아닌 검색 조건", {"searchConditions": "수분크림"})):
            with self.subTest(label):
                response = self.client.post("/api/v1/chat", json={"message": MESSAGE, **fields})

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "INVALID_CHAT_REQUEST")
        self.assertEqual(tools.calls, [])


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

    def test_skinType은_요청_값만_검색에_넘어가고_LLM이_넣은_값은_버린다(self):
        for label, request, expected in (("요청에 있음", {"skinType": "dry"}, "dry"), ("요청에 없음", {}, None)):
            with self.subTest(label):
                tools = serve(SEARCH, INVENTORY, FakeLlm(
                    tool_call("search_products", {"q": "수분크림", "skin_type": "oily"}),
                    final("찾았어요.", {})))
                self.client.post("/api/v1/chat", json={"message": MESSAGE, **request})

                self.assertEqual(tools.skin_types, [expected])
                self.assertEqual(self.traces()[-1]["skinType"], expected)

    def test_LLM이_고른_검색_인자를_검색_조건으로_싣고_서버가_정하는_값은_뺀다(self):
        serve(SEARCH, INVENTORY, FakeLlm(
            tool_call("search_products", {"q": "수분크림", "max_price": 30000, "limit": 20, "skin_type": "oily"}),
            final("찾았어요.", {})))
        body = self.chat().json()

        self.assertEqual(body["searchConditions"], {"q": "수분크림", "max_price": 30000})

    def test_검색_조건을_주면_LLM이_넣은_인자_대신_그_값으로_찾는다(self):
        conditions = {"q": "건성 피부에 끈적이지 않는 수분크림", "max_price": 30000, "product_types": ["크림"]}
        tools = serve(SEARCH, INVENTORY, FakeLlm(
            tool_call("search_products", {"q": "바디로션", "category": "바디케어"}),
            final("같은 조건으로 찾았어요.", {})))
        body = self.client.post("/api/v1/chat", json={"message": MESSAGE, "skinType": "dry",
                                                      "searchConditions": conditions}).json()

        self.assertEqual(tools.searched, [{**conditions, "limit": 5, "skin_type": "dry"}])
        self.assertEqual(body["searchConditions"], conditions)
        self.assertEqual(self.traces()[-1]["searchConditions"], conditions)

    def test_뺄_상품은_카드에도_LLM에게도_보이지_않는다(self):
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}), final("찾았어요.", {}))
        tools = serve(SEARCH, INVENTORY, llm)
        body = self.client.post("/api/v1/chat", json={"message": MESSAGE, "excludeProductIds": [1]}).json()

        self.assertEqual([p["productId"] for p in body["products"]], [2, 3])
        self.assertEqual([p["productId"] for p in json.loads(llm.requests[-1][-1]["content"])["products"]], [2, 3])
        self.assertEqual(tools.searched[0]["limit"], 6)

    def test_LLM이_막혀_규칙_답이_되어도_대안은_보낸_검색_조건으로_찾는다(self):
        conditions = {"q": "크림", "category": "스킨케어"}
        tools = serve(SEARCH, INVENTORY, FakeLlm(LlmError("429")))
        body = self.client.post("/api/v1/chat", json={"message": MESSAGE, "searchConditions": conditions,
                                                      "excludeProductIds": [1]}).json()

        self.assertEqual(body["answer"], "조건에 맞는 상품 1개를 찾았습니다.")
        self.assertEqual(tools.searched, [{**conditions, "limit": 6}])
        self.assertEqual(body["searchConditions"], conditions)

    def test_사진_주소는_카드에만_싣고_LLM에게는_넘기지_않는다(self):
        url = "https://image.msscdn.net/images/goods_img/20260930/1/1_1_500.jpg"
        small = url.replace("_500.", "_125.")
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}), final("찾았어요.", {}))
        serve({"products": [{**SEARCH["products"][0], "imageUrl": url, "thumbnailUrl": small}]}, INVENTORY, llm)
        body = self.chat().json()

        self.assertEqual((body["products"][0]["imageUrl"], body["products"][0]["thumbnailUrl"]), (url, small))
        self.assertEqual(llm.requests[-1][-1]["role"], "tool")
        self.assertNotIn("msscdn", llm.requests[-1][-1]["content"])

    def test_similarity는_LLM에게만_넘기고_카드에는_싣지_않는다(self):
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}), final("찾았어요.", {}))
        serve({"products": [{**SEARCH["products"][0], "similarity": 0.71}]}, INVENTORY, llm)
        body = self.chat().json()

        self.assertNotIn("similarity", body["products"][0])
        self.assertEqual(json.loads(llm.requests[-1][-1]["content"])["products"][0]["similarity"], 0.71)

    def test_검색은_두_번까지_부르고_세_번째는_오류로_돌려준다(self):
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                      tool_call("search_products", {"q": "보습 크림"}),
                      tool_call("search_products", {"q": "크림"}),
                      final("찾았어요.", {}))
        tools = serve(SEARCH, INVENTORY, llm)
        body = self.chat().json()

        self.assertEqual([call[1] for call in tools.calls], ["수분크림", "보습 크림"])
        self.assertIn("error", json.loads(llm.requests[-1][-1]["content"]))
        self.assertEqual(len(body["products"]), 3)

    def test_이유가_인용한_더_찾은_리뷰는_그_상품_근거_앞에_서고_인용하지_않으면_근거는_그대로다(self):
        found = {"reviewId": 19, "rating": 5, "excerpt": "…쓸수록 끈적임 없이 촉촉해요", "skinType": "dry"}
        for label, reason, expected in (
                ("인용함", "'끈적임 없이 촉촉해요'라는 리뷰가 있어요.", [found, SEARCH["products"][0]["evidence"][0]]),
                ("인용 안 함", "끈적이지 않는다는 리뷰가 있어요.", SEARCH["products"][0]["evidence"])):
            with self.subTest(label):
                llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                              tool_call("search_product_reviews", {"product_id": 1, "q": "끈적이지 않음"}),
                              final("찾았어요.", {"1": reason}))
                tools = serve(SEARCH, INVENTORY, llm)
                tools.reviews = {1: [found]}
                body = self.chat().json()

                self.assertEqual(tools.calls[-1], ("search_product_reviews", 1, "끈적이지 않음"))
                self.assertEqual(json.loads(llm.requests[-1][-1]["content"]), {"productId": 1, "reviews": [found]})
                self.assertEqual(body["products"][0]["evidence"], expected)
                self.assertEqual(body["products"][1]["evidence"], SEARCH["products"][1]["evidence"])

    def test_검색되지_않은_상품의_리뷰를_찾으면_LLM에게_오류로_돌려주고_카드는_그대로다(self):
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                      tool_call("search_product_reviews", {"product_id": 99, "q": "진정"}),
                      final("찾았어요.", {}))
        tools = serve(SEARCH, INVENTORY, llm)
        tools.reviews = {99: [{"reviewId": 991, "rating": 5, "excerpt": "진정돼요", "skinType": None}]}
        body = self.chat().json()

        self.assertIn("error", json.loads(llm.requests[-1][-1]["content"]))
        self.assertEqual([p["evidence"] for p in body["products"]], [p["evidence"] for p in SEARCH["products"]])

    def test_다시_검색해도_첫_검색의_가격_카테고리_브랜드_성분_조건은_그대로다(self):
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림", "max_price": 30000, "category": "스킨케어"}),
                      tool_call("search_products", {"q": "보습 크림", "max_price": 90000}),
                      final("찾았어요.", {}))
        tools = serve(SEARCH, INVENTORY, llm)
        body = self.chat().json()

        self.assertEqual(tools.searched[1], {"q": "보습 크림", "max_price": 30000, "category": "스킨케어", "limit": 5})
        self.assertEqual(body["searchConditions"], {"q": "보습 크림", "max_price": 30000, "category": "스킨케어"})

    def test_재고를_확인한_뒤의_검색은_오류로_돌려주고_카드는_처음_검색_결과다(self):
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                      tool_call("check_inventory", {"product_ids": [1, 2, 3]}),
                      tool_call("search_products", {"q": "보습 크림"}),
                      final("찾았어요.", {}))
        tools = serve(SEARCH, INVENTORY, llm)
        body = self.chat().json()

        self.assertEqual([call[1] for call in tools.calls if call[0] == "search_products"], ["수분크림"])
        self.assertIn("error", json.loads(llm.requests[-1][-1]["content"]))
        self.assertEqual(body["searchConditions"], {"q": "수분크림"})

    def test_마지막_라운드에는_도구를_더_부를_수_없다고_알린다(self):
        reviews = [tool_call("search_product_reviews", {"product_id": n, "q": "진정"}) for n in (1, 2, 3)]
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}), *reviews,
                      tool_call("check_inventory", {"product_ids": [1, 2, 3]}), final("찾았어요.", {}))
        serve(SEARCH, INVENTORY, llm)
        body = self.chat().json()

        self.assertEqual(body["answer"], "찾았어요.")
        self.assertEqual(llm.requests[-1][-1], {"role": "user", "content": agent.LAST_ROUND})
        self.assertEqual(llm.requests[-2][-1]["role"], "tool")

    def test_검색_조건이_정해진_요청에는_한_번만_검색하라고_알린다(self):
        conditions = {"q": "건성 피부에 끈적이지 않는 수분크림"}
        for label, extra, expected in (("조건 있음", {"searchConditions": conditions}, True), ("조건 없음", {}, False)):
            with self.subTest(label):
                llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}), final("찾았어요.", {}))
                serve(SEARCH, INVENTORY, llm)
                self.client.post("/api/v1/chat", json={"message": MESSAGE, **extra})

                self.assertEqual(agent.PINNED_CONDITIONS in llm.requests[0][0]["content"], expected)

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
        self.assertEqual(len(llm.requests), 2)

    def test_마감이_지난_뒤에는_도구를_부르지_않고_1B_규칙으로_답한다(self):
        # FakeLlm answers whatever time it is handed, as if its reply came back just at the deadline.
        llm = FakeLlm(tool_call("search_products", {"q": "보습크림"}), final("찾았어요.", {}))
        llm.timeout = 0
        tools = serve(SEARCH, INVENTORY, llm)
        body = self.chat().json()

        self.assertEqual(body["answer"], "조건에 맞는 상품 2개를 찾았습니다.")
        self.assertEqual(tools.calls, [("search_products", "수분크림", 30000, 5), ("check_inventory", [1, 2, 3])])

    def test_LLM_쪽이_막히면_같은_질문을_예비_LLM으로_처음부터_다시_한다(self):
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}), LlmError("503", provider_down=True),
                      model="main")
        fallback = FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                           final("예비가 골랐어요.", {"1": "촉촉하다는 리뷰가 있어요."}), model="fallback")
        serve(SEARCH, INVENTORY, llm, fallback)
        body = self.chat().json()

        self.assertEqual(body["answer"], "예비가 골랐어요.")
        self.assertEqual(body["products"][0]["reason"], "촉촉하다는 리뷰가 있어요.")
        # The fallback starts from the question, without the first LLM's tool calls.
        self.assertEqual([m["role"] for m in fallback.requests[0]], ["system", "user"])
        self.assertEqual([(t["model"], "error" in t) for t in self.traces()], [("main", True), ("fallback", False)])

    def test_답이_잘못됐을_때는_예비_LLM으로_넘어가지_않고_1B_규칙으로_답한다(self):
        llm = FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                      {"role": "assistant", "content": "수분크림 추천해요"})
        fallback = FakeLlm(final("쓰이면 안 돼요.", {}))
        serve(SEARCH, INVENTORY, llm, fallback)
        body = self.chat().json()

        self.assertEqual(body["answer"], "조건에 맞는 상품 2개를 찾았습니다.")
        self.assertEqual(fallback.requests, [])

    def test_예비_LLM은_처음_LLM이_쓰고_남은_시간만_쓴다(self):
        # The first call takes 0.3s of the 0.4s limit; the second runs out and the fallback gets about nothing.
        llm = SlowLlm(0.3, tool_call("search_products", {"q": "수분크림"}), final("늦었어요.", {}))
        llm.timeout = 0.4
        fallback = FakeLlm(tool_call("search_products", {"q": "수분크림"}), final("쓰이면 안 돼요.", {}))
        tools = serve(SEARCH, INVENTORY, llm, fallback)
        body = self.chat().json()

        self.assertEqual(body["answer"], "조건에 맞는 상품 2개를 찾았습니다.")
        self.assertEqual(len(fallback.requests), 1)
        self.assertEqual([call[0] for call in tools.calls],
                         ["search_products", "search_products", "check_inventory"])

    def test_LLM_경로에서_catalog가_내려가면_1B도_실패해_오류_본문을_반환한다(self):
        tools = serve(None, INVENTORY, FakeLlm(tool_call("search_products", {"q": "수분크림"}),
                                                final("검색이 안 돼요.", {})))
        response = self.chat()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "PRODUCT_SEARCH_FAILED")
        self.assertEqual([call[0] for call in tools.calls], ["search_products", "search_products"])


if __name__ == "__main__":
    unittest.main()
