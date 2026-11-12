"""Stage 1C: the LLM picks the MCP tools and writes answer and reasons (ADR-91, ADR-92).

Cards are built from what the tools actually returned, never from LLM text, so evidence and inventory stay the
catalog and order responses as the contract requires.
"""

import asyncio
import json
import re
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_service.config import settings
from agent_service.llm import Llm, LlmError
from agent_service.tools import McpTools, ToolError

# A search, a corrected one, evidence searches, the inventory check and the answer, with a round to spare (ADR-136).
MAX_ROUNDS = 6
SEARCH_LIMIT = 5
# One search and one corrected search (ADR-134); each more search costs another LLM round within the chat's limit.
MAX_SEARCHES = 2
# Search arguments the server sets itself, so they stay out of the conditions an alternative sends back (ADR-131).
SERVER_ARGUMENTS = {"limit", "skin_type"}
# The prompt keeps these from changing on a corrected search, yet the LLM dropped them all after an inventory check,
# so a corrected search carries the first search's ones (ADR-136).
FILTER_ARGUMENTS = {"max_price", "category", "brand", "exclude_ingredients"}
# Shown to the LLM to judge a search; the card contract has no such field (ADR-134).
SEARCH_ONLY_FIELDS = {"similarity"}
TRACE_PATH = Path(".local/chat-trace.jsonl")
UNKNOWN_INVENTORY = {"status": "UNKNOWN", "quantity": None, "estimatedDeliveryDate": None}
IMAGE_FIELDS = {"imageUrl", "thumbnailUrl"}
QUOTE = re.compile(r"['‘\"“]([^'’\"”]{2,})['’\"”]")
QUOTED_SHARE = 0.8

# The catalog matches q as one substring of names and reviews, so a multi-word q finds nothing.
KEYWORD_QUERY = """- search_products로 상품을 찾는다. q에는 띄어쓰기 없는 한 단어를 넣고, 가격 조건이 있으면 max_price에 원 단위 정수로 넣는다.
- 질문에 상품 유형(토너, 수분크림, 세럼, 선크림 등)이 있으면 q에는 그 유형을 넣는다. 효과(진정, 보습 등)는 상품 유형이 없을 때만 q에 넣는다."""
# Vector search compares q with whole reviews, so what a review would say about the product belongs in q (ADR-98).
SEMANTIC_QUERY = """- search_products로 상품을 찾는다. q에는 질문이 찾는 상품 유형과 리뷰에 나올 만한 조건(피부 타입, 사용감, 효과 등)을 질문에 쓰인 말로 한 문장에 넣는다. 가격·카테고리·브랜드·성분 조건은 q에 넣지 않고 각 인자에 넣는다. 가격 조건이 있으면 max_price에 원 단위 정수로 넣는다.
- 질문에 상품 유형이 있으면 product_types에 그 유형을 상품명에 쓰이는 짧은 말로 넣고, 같은 유형을 부르는 다른 말이 있으면 함께 넣는다. 꾸미는 말은 뺀다(수분크림이면 크림).
- 검색 결과를 받으면 질문에 맞는지 먼저 본다. 상품이 3개보다 적거나, 질문이 찾는 상품 유형이 아닌 상품이 절반을 넘으면 q나 product_types를 다른 말로 고쳐 search_products를 한 번 더 부른다. 가격·카테고리·브랜드·성분 조건은 바꾸지 않는다. similarity(0~1)는 상품마다 가장 가까운 리뷰가 q와 얼마나 가까운지 보여 주는 참고 값이다. 다시 검색은 한 번까지이고, 카드는 마지막 검색 결과로 만든다.
- 그다음 상품마다 근거 발췌가 질문의 조건(피부 타입, 사용감, 효과 등. 가격·카테고리·브랜드·성분은 빼고)을 말하는지 본다. 말하지 않는 조건이 있으면 다시 검색하지 말고 search_product_reviews에 그 상품의 productId와 그 조건을 리뷰에 쓰일 짧은 말(예: 진정, 끈적이지 않음)로 넣어 그 상품의 리뷰를 더 찾는다. 여러 상품을 한 번에 불러도 된다. 찾은 리뷰의 발췌도 그 상품의 근거로 쓸 수 있다. reason에는 근거로 쓴 발췌의 구절을 작은따옴표로 그대로 인용하고, 인용하지 않은 리뷰의 내용은 쓰지 않는다. 카드에는 인용한 리뷰만 근거로 나간다. 다시 검색과 search_product_reviews는 check_inventory보다 먼저 한다."""
# An alternative searches the first answer's conditions whatever the LLM asks for (ADR-131), so a second search
# would only repeat the first.
PINNED_CONDITIONS = "\n- 이번 요청은 검색 조건이 정해져 있어 다시 검색해도 결과가 같다. search_products는 한 번만 부른다."
# Some chats kept calling tools after the inventory check until the rounds ran out, and tool_choice "none" came back
# empty through the OpenAI-compatible endpoint (ADR-136).
LAST_ROUND = "이제 도구를 더 부를 수 없다. 지금까지 받은 결과로 마지막 답 JSON만 쓴다."
QUERY = SEMANTIC_QUERY if settings.search_backend == "opensearch" else KEYWORD_QUERY
SPLIT_RULE = "- 질문이 서로 다른 상품 유형을 둘 이상 찾으면(예: 토너랑 선크림) 처음에 search_products 대신 split_search를 한 번 부른다. 그 뒤에는 검색하지 않고, 받은 상품 전부로 check_inventory를 부른 다음 답한다. 하위 에이전트가 쓴 reason은 그대로 써도 된다."
FILTER_RULES = """- 질문이 찾는 상품의 카테고리가 분명하면 category에 그 카테고리 이름을, 브랜드를 말하면 brand에 브랜드 이름을 넣는다. 분명하지 않으면 비워 둔다.
- 질문이 어떤 성분이 빠진 상품을 원하면 exclude_ingredients에 그 성분을 넣는다."""
ANSWER_RULES = """- 마지막 답은 다른 글 없이 JSON 하나로만 쓴다: {"answer": "사용자에게 할 한두 문장", "reasons": {"<productId>": "추천 이유 한 문장"}}
- 검색된 상품은 화면에 모두 카드로 나간다. reasons에는 검색된 상품 하나하나에 빠짐없이 이유를 쓴다.
- reason은 그 상품 evidence의 리뷰 발췌에 실제로 쓰인 내용만 근거로 쓴다. 발췌에 없는 효과나 성분을 지어내지 않는다.
- 화면에는 productId가 보이지 않는다. answer에는 productId 숫자를 쓰지 않고, 상품을 가리킬 때는 상품 이름을 쓴다."""
# The split rule comes after the filter rules: put between the query and filter rules, it made the LLM drop the
# category in all three runs of one question (ADR-138).
SYSTEM_PROMPT = ("너는 화장품 쇼핑몰의 상품 추천 도우미다.\n" + QUERY + "\n" + FILTER_RULES + "\n" + SPLIT_RULE
                 + "\n- 상품을 추천하기 전에 찾은 상품의 productId 전부로 check_inventory를 불러 재고를 확인한다.\n"
                 + ANSWER_RULES + "\n- 상품 추천과 상관없는 말이면 도구를 부르지 말고 reasons를 빈 객체로 둔다.")
# A sub-agent finds one product type of a split question; the main agent checks inventory for all of them (ADR-138).
WORKER_PROMPT = ("너는 화장품 쇼핑몰의 상품 추천 도우미이고, 사용자 질문 가운데 한 상품 유형만 맡아 찾는다. 재고는 확인하지 않는다.\n"
                 + QUERY + "\n" + FILTER_RULES + "\n" + ANSWER_RULES)
SPLIT_SEARCH = "split_search"
SPLIT_TOOL = {"type": "function", "function": {
    "name": SPLIT_SEARCH,
    "description": "질문이 서로 다른 상품 유형을 둘 이상 찾을 때만 첫 검색 대신 부른다. 유형마다 하위 에이전트가 동시에 상품을 찾아 "
                   "상품과 추천 이유를 돌려준다.",
    "parameters": {"type": "object", "required": ["parts"], "properties": {"parts": {
        "type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 3,
        "description": "유형마다 그 상품 유형과 질문의 조건(피부 타입, 사용감, 가격, 성분 등)을 담은 질문 한 문장"}}}}}
# Tools the agent answers itself rather than an MCP server; the measurement's control arm empties it.
LOCAL_TOOLS = [SPLIT_TOOL]
WORKER_TOOLS = {"search_products", "search_product_reviews"}
MAX_PARTS = 3
AFTER_INVENTORY = "check_inventory 뒤에는 search_products를 부르지 않는다. 지금 검색 결과로 답한다"
AFTER_SPLIT = "split_search 뒤에는 search_products를 부르지 않는다. 받은 상품으로 check_inventory를 부르고 답한다"
# order-service dates deliveries in Seoul, which has no daylight saving time, so a fixed offset needs no tz data.
SEOUL = timezone(timedelta(hours=9))
TODAY_RULE = "\n- 오늘은 {today}이다. check_inventory의 estimatedDeliveryDate가 오늘 다음 날이면 내일 도착이다."


async def run_agent(message: str, llm: Llm, tools: McpTools, skin_type: str | None = None,
                    deadline: float | None = None, conditions: dict[str, Any] | None = None,
                    exclude: Sequence[int] = ()
                    ) -> tuple[str, list[dict], dict[int, dict], dict[int, str], dict[str, Any] | None]:
    """Return answer, the last searched products, inventories, reasons and the conditions of that search.

    Raises LlmError when the LLM cannot finish or no search succeeded. A failed search can be the LLM's bad arguments
    as well as catalog being down, so it is left to the 1B fallback, whose own search tells the two apart.
    deadline (time.monotonic()) defaults to llm.timeout from now; a fallback LLM gets what the first one left.
    An alternative to a sold-out product passes the first answer's conditions, searched whatever the LLM asks for,
    and the products to exclude (ADR-131).
    """
    trace: dict[str, Any] = {"model": llm.model, "message": message, "skinType": skin_type,
                             "searchConditions": conditions, "excludeProductIds": list(exclude), "calls": [],
                             "usage": []}
    started = time.monotonic()
    try:
        answer, products, inventories, reasons, searched = await _loop(
            message, llm, tools, trace, skin_type, deadline or time.monotonic() + llm.timeout, conditions, exclude)
        trace.update(answer=answer, reasons={
            str(product_id): {"reason": reason, "inSearch": product_id in {p["productId"] for p in products},
                              "evidence": next((p["evidence"] for p in products if p["productId"] == product_id), [])}
            for product_id, reason in reasons.items()
        })
        return answer, products, inventories, reasons, searched
    except LlmError as error:
        trace["error"] = repr(error)
        raise
    finally:
        trace["elapsedMs"] = round((time.monotonic() - started) * 1000)
        _write_trace(trace)


async def _loop(message: str, llm: Llm, tools: McpTools, trace: dict[str, Any], skin_type: str | None,
                deadline: float, conditions: dict[str, Any] | None, exclude: Sequence[int],
                system: str | None = None, allowed: set[str] | None = None
                ) -> tuple[str, list[dict], dict[int, dict], dict[int, str], dict[str, Any] | None]:
    """The main agent's loop, or a sub-agent's when given its own system prompt and the tools it may call."""
    if system is None:
        system = (SYSTEM_PROMPT
                  + (PINNED_CONDITIONS if conditions is not None else "")
                  + TODAY_RULE.format(today=datetime.now(SEOUL).date().isoformat()))
        definitions = tools.definitions + (LOCAL_TOOLS if conditions is None else [])
    else:
        definitions = [d for d in tools.definitions if d["function"]["name"] in (allowed or set())]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": message}]
    products: list[dict] | None = None
    searched = conditions
    inventories: dict[int, dict] = {}
    found: dict[int, list[dict]] = {}
    filters: dict[str, Any] = {}
    split_reasons: dict[int, str] | None = None
    search_failed = False
    # The limit covers the whole chat so the screen has one wait to plan for. Tool calls are not cut short: the one
    # running at the deadline goes on to its own limit (CALL_TIMEOUT_SECONDS), and the 1B fallback then makes its own
    # search and inventory calls, so the chat can overrun by up to three tool calls.
    for round_number in range(MAX_ROUNDS):
        if round_number == MAX_ROUNDS - 1:
            messages.append({"role": "user", "content": LAST_ROUND})
        reply, usage = await llm.complete(messages, definitions, timeout=deadline - time.monotonic())
        trace["usage"].append(usage)
        if not isinstance(reply, dict):
            raise LlmError(f"assistant message is not an object: {reply!r}")
        calls = reply.get("tool_calls") or []
        if not calls:
            answer, reasons = final_answer(reply.get("content"))
            break
        messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls})
        for call in calls:
            if time.monotonic() >= deadline:
                raise LlmError("no time left for another tool call")
            try:
                call_id, name, raw_arguments = call["id"], call["function"]["name"], call["function"]["arguments"]
            except (KeyError, TypeError) as error:
                raise LlmError(f"malformed tool call: {call!r}") from error
            # gpt-oss sometimes leaks its channel marker into the name: "search_products<|channel|>commentary".
            name = name.split("<|", 1)[0]
            if name == SPLIT_SEARCH:
                result, parts_products, parts_reasons = await _split(raw_arguments, llm, tools, trace, skin_type,
                                                                     deadline, products)
                if parts_products is not None:
                    products, searched, split_reasons = parts_products, None, parts_reasons
            else:
                blocked = AFTER_INVENTORY if inventories else AFTER_SPLIT if split_reasons is not None else None
                result, arguments = await _call_tool(tools, name, raw_arguments, trace, skin_type, conditions,
                                                     filters, blocked, exclude)
            if name == "search_products":
                if "error" in result:
                    search_failed = True
                else:
                    products = result["products"]
                    searched = {k: v for k, v in arguments.items() if k not in SERVER_ARGUMENTS}
                    filters = filters or {k: v for k, v in searched.items() if k in FILTER_ARGUMENTS}
            elif name == "check_inventory" and "error" not in result:
                inventories.update(inventory_by_id(result))
            elif name == "search_product_reviews" and "error" not in result:
                if result["productId"] in {p["productId"] for p in products or []}:
                    found.setdefault(result["productId"], []).extend(result["reviews"])
                else:
                    result = {"error": f"productId {result['productId']}은 검색된 상품이 아니다"}
            messages.append({"role": "tool", "tool_call_id": call_id,
                             "content": json.dumps(_without_images(result), ensure_ascii=False)})
    else:
        raise LlmError(f"no final answer after {MAX_ROUNDS} rounds")
    if products is None and search_failed:
        raise LlmError("every search_products call failed")
    reasons = {**(split_reasons or {}), **reasons}
    return answer, with_cited_evidence(products or [], found, reasons), inventories, reasons, searched


async def _split(raw_arguments: str, llm: Llm, tools: McpTools, trace: dict[str, Any], skin_type: str | None,
                 deadline: float, products: list[dict] | None
                 ) -> tuple[dict[str, Any], list[dict] | None, dict[int, str]]:
    """Run a sub-agent per part at once and merge their cards, the parts sharing the five cards in order (ADR-138).

    Returns what the main LLM is shown, the merged products and the sub-agents' reasons; products is None on error.
    """
    entry: dict[str, Any] = {"name": SPLIT_SEARCH, "arguments": raw_arguments}
    trace["calls"].append(entry)
    try:
        if products is not None:
            raise ValueError("split_search는 첫 검색 전에만 부른다")
        parts = json.loads(raw_arguments or "{}")["parts"]
        if not (isinstance(parts, list) and 2 <= len(parts) <= MAX_PARTS
                and all(isinstance(part, str) and part.strip() for part in parts)):
            raise ValueError(f"parts는 질문 문장 2~{MAX_PARTS}개다")
    except (ValueError, KeyError, TypeError) as error:
        entry["error"] = str(error)
        return {"error": entry["error"]}, None, {}
    workers = await asyncio.gather(*[_worker(part, llm, tools, skin_type, deadline) for part in parts])
    trace["parts"] = [sub for sub, _, _ in workers]
    merged: list[dict] = []
    reasons: dict[int, str] = {}
    shown = []
    for n, (part, (_, found_products, found_reasons)) in enumerate(zip(parts, workers)):
        size = SEARCH_LIMIT // len(parts) + (n < SEARCH_LIMIT % len(parts))
        taken = {p["productId"] for p in merged}
        kept = [p for p in found_products if p["productId"] not in taken][:size]
        merged += kept
        reasons.update({p["productId"]: found_reasons[p["productId"]] for p in kept if p["productId"] in found_reasons})
        shown.append({"part": part, "products": [
            {**{k: v for k, v in p.items() if k not in IMAGE_FIELDS}, "reason": found_reasons.get(p["productId"])}
            for p in kept]})
    if not merged:
        entry["error"] = "하위 에이전트가 상품을 찾지 못했다"
        return {"error": entry["error"]}, None, {}
    return {"parts": shown}, merged, reasons


async def _worker(part: str, llm: Llm, tools: McpTools, skin_type: str | None,
                  deadline: float) -> tuple[dict[str, Any], list[dict], dict[int, str]]:
    """One sub-agent: the same loop with the search tools only. A failure leaves its part empty, not the chat."""
    sub: dict[str, Any] = {"part": part, "calls": [], "usage": []}
    started = time.monotonic()
    try:
        _, products, _, reasons, _ = await _loop(part, llm, tools, sub, skin_type, deadline, None, (),
                                                 system=WORKER_PROMPT, allowed=WORKER_TOOLS)
        return sub, products, reasons
    except LlmError as error:
        sub["error"] = repr(error)
        return sub, [], {}
    finally:
        sub["elapsedMs"] = round((time.monotonic() - started) * 1000)


async def _call_tool(tools: McpTools, name: str, raw_arguments: str, trace: dict[str, Any], skin_type: str | None,
                     conditions: dict[str, Any] | None, filters: dict[str, Any], blocked: str | None,
                     exclude: Sequence[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the result and the chosen arguments, an alternative's conditions in place of the LLM's search arguments
    and the first search's filters over a corrected search's.

    Tool failures go back to the LLM as an error result so it can retry or answer without them.
    """
    entry: dict[str, Any] = {"name": name, "arguments": raw_arguments}
    trace["calls"].append(entry)
    if name == "search_products" and sum(c["name"] == name for c in trace["calls"]) > MAX_SEARCHES:
        entry["error"] = f"search_products는 대화 하나에 {MAX_SEARCHES}번까지만 부를 수 있다"
        return {"error": entry["error"]}, {}
    # Searching after the inventory check left cards without inventory and ran a chat out of rounds (ADR-136); after a
    # split it would replace the merged cards (ADR-138).
    if name == "search_products" and blocked:
        entry["error"] = blocked
        return {"error": entry["error"]}, {}
    try:
        arguments = json.loads(raw_arguments or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a JSON object")
    except ValueError as error:
        entry["error"] = f"invalid arguments: {error}"
        return {"error": entry["error"]}, {}
    if name == "search_products":
        arguments = conditions if conditions is not None else {**arguments, **filters}
    try:
        if name == "search_products":
            return await search(tools, arguments, skin_type, exclude), arguments
        return await tools.call(name, arguments), arguments
    except ToolError as error:
        entry["error"] = str(error)
        return {"error": entry["error"]}, arguments


async def search(tools: McpTools, arguments: dict[str, Any], skin_type: str | None,
                 exclude: Sequence[int] = ()) -> dict[str, Any]:
    """Search as the server requires, whether the LLM, the rules or an earlier answer chose the arguments.

    Every searched product becomes a card, so the server sets the count whatever limit was asked for, and the skin type
    is the one the request chose (ADR-120). Excluded products, sold out a moment ago, are searched past to keep the
    cards full and dropped before the LLM or the cards see them (ADR-131).
    """
    arguments = {**arguments, "limit": SEARCH_LIMIT + len(exclude)}
    arguments.pop("skin_type", None)
    if skin_type is not None:
        arguments["skin_type"] = skin_type
    result = await tools.call("search_products", arguments)
    return {**result, "products": [p for p in result["products"] if p["productId"] not in exclude][:SEARCH_LIMIT]}


def with_cited_evidence(products: list[dict], found: dict[int, list[dict]], reasons: dict[int, str]) -> list[dict]:
    """Put the reviews a reason quotes ahead of its product's evidence, keeping two, so the card shows the reviews the
    reason was written from, search_product_reviews' finds among them (ADR-136). An unquoted reason keeps the evidence.

    >>> products = [{"productId": 1, "evidence": [{"reviewId": 1, "excerpt": "촉촉해요"}, {"reviewId": 2, "excerpt": "무난"}]}]
    >>> found = {1: [{"reviewId": 9, "excerpt": "…며칠 쓰면 진정이 돼요"}]}
    >>> cited = with_cited_evidence(products, found, {1: "'진정이 돼요'와 '촉촉 해요'라는 리뷰가 있어요."})
    >>> [e["reviewId"] for e in cited[0]["evidence"]]
    [9, 1]
    >>> with_cited_evidence(products, found, {1: "촉촉하다는 리뷰가 있어요."}) == products
    True
    """
    result = []
    for product in products:
        pool = product["evidence"] + found.get(product["productId"], [])
        cited: list[dict] = []
        for quote in QUOTE.findall(reasons.get(product["productId"], "")):
            review = next((e for e in pool if quotes(e["excerpt"], quote)), None)
            if review is not None and review not in cited:
                cited.append(review)
        result.append({**product, "evidence": (cited + [e for e in product["evidence"] if e not in cited])[:2]})
    return result


def quotes(excerpt: str, quote: str) -> bool:
    """Whether most words of the quote are in the excerpt: the LLM drops words inside its quotes and elides with dots.

    >>> quotes("피부가 예민한 편이어서 피부가 자주 따갑고", "피부가 예민한 편이어서 자주 따갑고")
    True
    >>> quotes("가볍고 닦토용으로도 좋아요 당기지 않아요", "가볍고 ... 당기지 않아요"), quotes("촉촉해요", "끈적임 없어요")
    (True, False)
    """
    words = [word for word in re.split(r"\s+|\.{2,}|…", quote) if word]
    return sum(word in excerpt for word in words) >= QUOTED_SHARE * len(words)


def _without_images(result: dict[str, Any]) -> dict[str, Any]:
    """Image addresses are for the cards; on every search they would only cost the LLM tokens (ADR-127)."""
    if "products" not in result:
        return result
    return {**result, "products": [{k: v for k, v in p.items() if k not in IMAGE_FIELDS}
                                   for p in result["products"]]}


def final_answer(content: Any) -> tuple[str, dict[int, str]]:
    """Parse the closing JSON. Text around it is ignored; anything else unusable is an LlmError.

    >>> final_answer('결과입니다 {"answer": "2개 찾았어요", "reasons": {"1": "촉촉하다는 리뷰", "2": " "}}')
    ('2개 찾았어요', {1: '촉촉하다는 리뷰'})
    >>> final_answer('{"answer": "안녕하세요", "reasons": {}}')
    ('안녕하세요', {})
    >>> final_answer('{"answer": "골랐어요", "reasons": {"179": "후기: \\\\\\'가벼워요\\\\\\'"}}')
    ('골랐어요', {179: "후기: '가벼워요'"})
    >>> final_answer("그냥 문장")
    Traceback (most recent call last):
    ...
    agent_service.llm.LlmError: final answer is not the agreed JSON: '그냥 문장'
    """
    try:
        # gpt-oss quotes reviews with \' inside reasons, which JSON does not allow.
        text = content[content.index("{"):content.rindex("}") + 1].replace("\\'", "'")
        final = json.loads(text)
        answer = final["answer"]
        reasons = {int(product_id): reason.strip() for product_id, reason in (final.get("reasons") or {}).items()
                   if isinstance(reason, str) and reason.strip()}
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("answer is empty")
    except (AttributeError, TypeError, ValueError, KeyError) as error:
        raise LlmError(f"final answer is not the agreed JSON: {content!r}") from error
    return answer.strip(), reasons


def inventory_by_id(checked: dict[str, Any]) -> dict[int, dict]:
    return {
        item["productId"]: {k: item[k] for k in ("status", "quantity", "estimatedDeliveryDate")}
        for item in checked["inventories"]
    }


def cards(products: list[dict], inventories: dict[int, dict], reasons: dict[int, str]) -> list[dict]:
    """NOT_FOUND products are dropped; a missing inventory means UNKNOWN so an order failure never looks sold out."""
    result = []
    for product in products:
        inventory = inventories.get(product["productId"], UNKNOWN_INVENTORY)
        if inventory["status"] == "NOT_FOUND":
            continue
        # The contract never allows a reason without evidence to back it.
        reason = reasons.get(product["productId"]) if product["evidence"] else None
        card = {k: v for k, v in product.items() if k not in SEARCH_ONLY_FIELDS}
        result.append({**card, "reason": reason, "inventory": inventory})
    return result


def _write_trace(trace: dict[str, Any]) -> None:
    """One JSON line per chat: generated text next to the reviews it claims, for measuring misbehaviour later."""
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(trace, ensure_ascii=False) + "\n")
