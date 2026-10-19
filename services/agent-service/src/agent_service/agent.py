"""Stage 1C: the LLM picks the MCP tools and writes answer and reasons (ADR-91, ADR-92).

Cards are built from what the tools actually returned, never from LLM text, so evidence and inventory stay the
catalog and order responses as the contract requires.
"""

import json
import time
from pathlib import Path
from typing import Any

from agent_service.llm import Llm, LlmError
from agent_service.tools import McpTools, ToolError

MAX_ROUNDS = 5
SEARCH_LIMIT = 5
TRACE_PATH = Path(".local/chat-trace.jsonl")
UNKNOWN_INVENTORY = {"status": "UNKNOWN", "quantity": None, "estimatedDeliveryDate": None}

# The catalog matches q as one substring of names and reviews, so a multi-word q finds nothing.
SYSTEM_PROMPT = """너는 화장품 쇼핑몰의 상품 추천 도우미다.
- search_products로 상품을 찾는다. q에는 띄어쓰기 없는 한 단어를 넣고, 가격 조건이 있으면 max_price에 원 단위 정수로 넣는다.
- 질문에 상품 유형(토너, 수분크림, 세럼, 선크림 등)이 있으면 q에는 그 유형을 넣는다. 효과(진정, 보습 등)는 상품 유형이 없을 때만 q에 넣는다.
- 질문이 찾는 상품의 카테고리가 분명하면 category에 그 카테고리 이름을, 브랜드를 말하면 brand에 브랜드 이름을 넣는다. 분명하지 않으면 비워 둔다.
- 질문이 어떤 성분이 빠진 상품을 원하면 exclude_ingredients에 그 성분을 넣는다.
- 상품을 추천하기 전에 찾은 상품의 productId 전부로 check_inventory를 불러 재고를 확인한다.
- 마지막 답은 다른 글 없이 JSON 하나로만 쓴다: {"answer": "사용자에게 할 한두 문장", "reasons": {"<productId>": "추천 이유 한 문장"}}
- 검색된 상품은 화면에 모두 카드로 나간다. reasons에는 검색된 상품 하나하나에 빠짐없이 이유를 쓴다.
- reason은 그 상품 evidence의 리뷰 발췌에 실제로 쓰인 내용만 근거로 쓴다. 발췌에 없는 효과나 성분을 지어내지 않는다.
- 상품 추천과 상관없는 말이면 도구를 부르지 말고 reasons를 빈 객체로 둔다."""


async def run_agent(message: str, llm: Llm, tools: McpTools) -> tuple[str, list[dict], dict[int, dict], dict[int, str]]:
    """Return answer, the last searched products, inventories and reasons.

    Raises LlmError when the LLM cannot finish or no search succeeded. A failed search can be the LLM's bad arguments
    as well as catalog being down, so it is left to the 1B fallback, whose own search tells the two apart.
    """
    trace: dict[str, Any] = {"message": message, "calls": [], "usage": []}
    started = time.monotonic()
    try:
        answer, products, inventories, reasons = await _loop(message, llm, tools, trace)
        trace.update(answer=answer, reasons={
            str(product_id): {"reason": reason, "inSearch": product_id in {p["productId"] for p in products},
                              "evidence": next((p["evidence"] for p in products if p["productId"] == product_id), [])}
            for product_id, reason in reasons.items()
        })
        return answer, products, inventories, reasons
    except LlmError as error:
        trace["error"] = repr(error)
        raise
    finally:
        trace["elapsedMs"] = round((time.monotonic() - started) * 1000)
        _write_trace(trace)


async def _loop(message: str, llm: Llm, tools: McpTools,
                trace: dict[str, Any]) -> tuple[str, list[dict], dict[int, dict], dict[int, str]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT},
                                      {"role": "user", "content": message}]
    products: list[dict] | None = None
    inventories: dict[int, dict] = {}
    search_failed = False
    for _ in range(MAX_ROUNDS):
        reply, usage = await llm.complete(messages, tools.definitions)
        trace["usage"].append(usage)
        if not isinstance(reply, dict):
            raise LlmError(f"assistant message is not an object: {reply!r}")
        calls = reply.get("tool_calls") or []
        if not calls:
            answer, reasons = final_answer(reply.get("content"))
            break
        messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls})
        for call in calls:
            try:
                call_id, name, raw_arguments = call["id"], call["function"]["name"], call["function"]["arguments"]
            except (KeyError, TypeError) as error:
                raise LlmError(f"malformed tool call: {call!r}") from error
            # gpt-oss sometimes leaks its channel marker into the name: "search_products<|channel|>commentary".
            name = name.split("<|", 1)[0]
            result = await _call_tool(tools, name, raw_arguments, trace)
            if name == "search_products":
                if "error" in result:
                    search_failed = True
                else:
                    products = result["products"]
            elif name == "check_inventory" and "error" not in result:
                inventories.update(inventory_by_id(result))
            messages.append({"role": "tool", "tool_call_id": call_id,
                             "content": json.dumps(result, ensure_ascii=False)})
    else:
        raise LlmError(f"no final answer after {MAX_ROUNDS} rounds")
    if products is None and search_failed:
        raise LlmError("every search_products call failed")
    return answer, products or [], inventories, reasons


async def _call_tool(tools: McpTools, name: str, raw_arguments: str, trace: dict[str, Any]) -> dict[str, Any]:
    """Tool failures go back to the LLM as an error result so it can retry or answer without them."""
    entry: dict[str, Any] = {"name": name, "arguments": raw_arguments}
    trace["calls"].append(entry)
    try:
        arguments = json.loads(raw_arguments or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a JSON object")
    except ValueError as error:
        entry["error"] = f"invalid arguments: {error}"
        return {"error": entry["error"]}
    # Every searched product becomes a card, so the server caps the count whatever limit the LLM asked for.
    if name == "search_products":
        arguments["limit"] = SEARCH_LIMIT
    try:
        return await tools.call(name, arguments)
    except ToolError as error:
        entry["error"] = str(error)
        return {"error": entry["error"]}


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
        result.append({**product, "reason": reason, "inventory": inventory})
    return result


def _write_trace(trace: dict[str, Any]) -> None:
    """One JSON line per chat: generated text next to the reviews it claims, for measuring misbehaviour later."""
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(trace, ensure_ascii=False) + "\n")
