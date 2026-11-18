"""Questions whose answers the catalog data decides, so hundreds are scored without a judge (ADR-176).

uv run --package agent-service python eval/quant.py build                                  # eval/quant-questions.json
uv run --package agent-service python eval/quant.py build-pairs                            # eval/quant-pair-questions.json
uv run --package agent-service python eval/quant.py run .local/eval/quant/vector.json      # one chat per question
uv run --package agent-service python eval/quant.py run .local/eval/quant/pairs.json pairs # the pair questions
uv run --package agent-service python eval/quant.py replay .local/eval/quant/vector.json .local/eval/quant/hybrid.json

A question asks for one product type with one quality that shoppers rated in Musinsa's review survey, sometimes under
a price. A product is right when it is of that type, within the price, and at least SHARE of its survey answers, at
least MIN_ANSWERS of them, rate the quality well. With fewer answers nobody can tell, so it is counted apart as
unknown. The search never reads the survey answers, only the review text.

A pair question asks for two qualities at once (ADR-173's question types). It is right when both are rated well by the
same rule, wrong when either is known to fall short, and unknown otherwise.

"replay" searches again with the arguments the LLM chose in a saved run, through agent.search as a live chat does, so
two search backends are compared on the same arguments without the LLM's run-to-run differences.
Needs catalog-db, opensearch, catalog-service (8081) and, for "run", order-service (8082) and the LLM settings.
"""

import asyncio
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pool import ROOT, literal, sql  # noqa: E402

QUESTIONS = ROOT / "eval/quant-questions.json"
PAIR_QUESTIONS = ROOT / "eval/quant-pair-questions.json"
MIN_ANSWERS = 30
SHARE = 0.8
# A question is kept when the data can tell enough products apart: this many with enough answers, right and wrong.
MIN_JUDGED, MIN_RIGHT, MIN_WRONG = 10, 5, 3
# Survey answers that do not rate the quality well, spaces removed. Other answers belong to other survey questions.
NOT_GOOD = ["보통", "낮음", "매우낮음", "나쁨", "매우나쁨", "약간있음", "매우있음"]
# Category code, the type as a shopper asks for it, words a product name of that type has, words it must not have.
TYPES = [
    ("104001", "크림", ["크림"], []),
    ("104001", "토너", ["토너"], ["패드"]),
    ("104001", "세럼", ["세럼", "앰플", "에센스"], []),
    ("104001", "로션", ["로션", "에멀전"], []),
    ("104001", "토너 패드", ["패드"], []),
    ("104001", "미스트", ["미스트"], []),
    ("104002", "선크림", ["크림", "세럼", "로션", "젤", "에센스", "플루이드"], ["스틱", "쿠션", "스프레이", "패치"]),
    ("104003", "클렌징 폼", ["폼"], []),
    ("104003", "클렌징 오일", ["오일"], ["밤"]),
    ("104003", "클렌징 워터", ["워터"], []),
    ("104003", "클렌징 밤", ["밤"], []),
    ("104006", "샴푸", ["샴푸"], []),
    ("104006", "트리트먼트", ["트리트먼트"], ["샴푸"]),
    ("104006", "헤어 에센스", ["에센스", "오일", "세럼"], ["샴푸", "트리트먼트"]),
    ("104007", "바디로션", ["로션"], []),
    ("104007", "바디워시", ["워시"], []),
    ("104007", "핸드크림", ["핸드크림"], []),
    ("104013", "마스크팩", ["마스크", "팩"], []),
    ("104014", "쿠션", ["쿠션"], []),
    ("104014", "파운데이션", ["파운데이션"], []),
    ("104015", "립밤", ["립밤"], []),
    ("104015", "틴트", ["틴트"], []),
    ("104015", "립스틱", ["립스틱"], []),
    ("104016", "마스카라", ["마스카라"], []),
    ("104016", "아이섀도우", ["섀도우", "팔레트"], []),
    ("104005", "향수", ["퍼퓸", "향수", "오드"], []),
]
# Survey attribute: the answers that rate it well (spaces removed) and two ways a shopper asks for it.
QUALITIES = {
    "보습력": (["매우높음", "높음", "매우좋음", "좋음"], ["보습력 좋은 {t}", "촉촉한 {t}"]),
    "자극여부": (["전혀없음", "거의없음"], ["자극 없는 {t}", "순한 {t}"]),
    "끈적임 여부": (["전혀없음", "거의없음"], ["끈적이지 않는 {t}", "끈적임 없는 {t}"]),
    "흡수력": (["매우좋음", "좋음", "매우만족", "만족"], ["흡수 잘 되는 {t}", "빨리 흡수되는 {t}"]),
    "지속력": (["매우높음", "높음", "매우좋음", "좋음"], ["지속력 좋은 {t}", "오래 가는 {t}"]),
    "향 만족도": (["매우좋음", "좋음"], ["향 좋은 {t}", "향이 좋다는 평이 많은 {t}"]),
    "발림성": (["매우좋음", "좋음"], ["발림성 좋은 {t}", "부드럽게 발리는 {t}"]),
    "세정력": (["매우좋음", "좋음"], ["세정력 좋은 {t}", "잘 지워지는 {t}"]),
    "발색력": (["매우높음", "높음"], ["발색 좋은 {t}", "발색력 좋은 {t}"]),
    "밀착력": (["매우높음", "높음"], ["밀착력 좋은 {t}", "잘 밀착되는 {t}"]),
    "커버력": (["매우높음", "높음"], ["커버력 좋은 {t}", "잘 가려지는 {t}"]),
    "모발상태": (["매우좋음", "좋음"], ["머릿결이 좋아지는 {t}", "모발 상태가 좋아졌다는 평이 많은 {t}"]),
    "진정효과": (["매우높음", "높음"], ["진정 효과 좋은 {t}", "진정에 좋은 {t}"]),
}
# The first quality of a pair question, joined to the second: "촉촉하고 끈적이지 않는 크림".
JOINED = {"보습력": "촉촉하고", "자극여부": "자극 없고", "끈적임 여부": "끈적이지 않고", "흡수력": "흡수 잘 되고",
          "지속력": "오래 가고", "향 만족도": "향 좋고", "발림성": "부드럽게 발리고", "세정력": "잘 지워지고",
          "발색력": "발색 좋고", "밀착력": "잘 밀착되고", "커버력": "커버력 좋고", "모발상태": "머릿결이 좋아지고",
          "진정효과": "진정 효과 좋고"}
_truths: dict[tuple, dict[int, tuple[int, int, int]]] = {}


def truth(q: dict) -> dict[int, tuple[int, int, int]]:
    """Every product of the asked type: its price, its survey answers on the quality and how many rate it well."""
    key = (q["category"], *q["typeNames"], "|", *q["excludeNames"], q["attribute"])
    if key not in _truths:
        def compact(word: str) -> str:
            return literal("%" + word.replace(" ", "") + "%")
        names = " or ".join(f"replace(p.name, ' ', '') ilike {compact(n)}" for n in q["typeNames"])
        excluded = "".join(f" and replace(p.name, ' ', '') not ilike {compact(n)}" for n in q["excludeNames"])
        good = ", ".join(literal(a) for a in q["good"])
        scale = ", ".join(literal(a) for a in q["good"] + NOT_GOOD)
        rows = sql(f"select p.id, p.price, count(s.review_id), "
                   f"count(s.review_id) filter (where replace(s.answer, ' ', '') in ({good})) from products p "
                   f"left join reviews r on r.product_id = p.id left join review_survey_answers s "
                   f"on s.review_id = r.id and s.attribute = {literal(q['attribute'])} "
                   f"and replace(s.answer, ' ', '') in ({scale}) "
                   f"where p.category_code = {literal(q['category'])} and ({names}){excluded} group by p.id")
        _truths[key] = {int(i): (int(price), int(answers), int(rated_well))
                        for i, price, answers, rated_well in (row.split("|") for row in rows.splitlines() if row)}
    return _truths[key]


def judge(q: dict, product_id: int) -> str:
    """
    >>> _truths[("C", "T", "|", "A")] = {1: (100, 40, 36), 2: (100, 40, 20), 3: (100, 5, 5)}
    >>> _truths[("C", "T", "|", "B")] = {1: (100, 40, 36), 2: (100, 40, 36), 3: (100, 40, 36)}
    >>> q = {"category": "C", "typeNames": ["T"], "excludeNames": [], "maxPrice": None, "attributes": ["A", "B"]}
    >>> [judge(q, i) for i in (1, 2, 3, 4)]
    ['right', 'wrong', 'unknown', 'wrong']
    """
    if "attributes" in q:
        one = {k: v for k, v in q.items() if k != "attributes"}
        verdicts = [judge({**one, "attribute": a, "good": QUALITIES.get(a, ([],))[0]}, product_id)
                    for a in q["attributes"]]
        return "wrong" if "wrong" in verdicts else "unknown" if "unknown" in verdicts else "right"
    found = truth(q).get(product_id)
    if found is None:  # another category or another type
        return "wrong"
    price, answers, rated_well = found
    if q["maxPrice"] and price > q["maxPrice"]:
        return "wrong"
    if answers < MIN_ANSWERS:
        return "unknown"
    return "right" if rated_well / answers >= SHARE else "wrong"


def build() -> None:
    questions = []
    for category, asked, names, excludes in TYPES:
        for attribute, (good, phrasings) in QUALITIES.items():
            base = {"category": category, "type": asked, "typeNames": names, "excludeNames": excludes,
                    "attribute": attribute, "good": good}
            judged = [(price, rated_well / answers >= SHARE) for price, answers, rated_well in truth(base).values()
                      if answers >= MIN_ANSWERS]
            if not judged:
                continue
            # Asked once without a price and once under the middle price of the products the data can tell apart.
            for cap in (None, max(10000, int(round(statistics.median(price for price, _ in judged), -4)))):
                kept = [right for price, right in judged if cap is None or price <= cap]
                if len(kept) < MIN_JUDGED or sum(kept) < MIN_RIGHT or len(kept) - sum(kept) < MIN_WRONG:
                    continue
                for phrasing in phrasings:
                    text = phrasing.format(t=asked) + (f" {cap // 10000}만원 이하로" if cap else "") + " 추천해 줘"
                    questions.append({"id": f"N{len(questions) + 1:03d}", "text": text, **base, "maxPrice": cap,
                                      "judged": len(kept), "right": sum(kept)})
    QUESTIONS.write_text(json.dumps({
        "version": "2026-11-18", "rule": f"right when of the type, within the price and at least {SHARE:.0%} of at "
        f"least {MIN_ANSWERS} survey answers rate the quality well; fewer answers is unknown",
        "questions": questions}, ensure_ascii=False, indent=1))
    print(len(questions), "questions,", len({(q["category"], q["type"], q["attribute"]) for q in questions}),
          "type and quality pairs,", json.dumps(Counter(q["attribute"] for q in questions), ensure_ascii=False))


def build_pairs() -> None:
    """Two qualities of one type, kept by the same rules as build(): enough products with both answered."""
    questions = []
    for category, asked, names, excludes in TYPES:
        base = {"category": category, "type": asked, "typeNames": names, "excludeNames": excludes}
        rated = {a: truth({**base, "attribute": a, "good": good}) for a, (good, _) in QUALITIES.items()}
        for n, first in enumerate(QUALITIES):
            for second in list(QUALITIES)[n + 1:]:
                judged = [(price, a_well / a_all >= SHARE and b_well / b_all >= SHARE)
                          for i, (price, a_all, a_well) in rated[first].items()
                          for _, b_all, b_well in [rated[second][i]] if a_all >= MIN_ANSWERS and b_all >= MIN_ANSWERS]
                if not judged:
                    continue
                for cap in (None, max(10000, int(round(statistics.median(price for price, _ in judged), -4)))):
                    kept = [right for price, right in judged if cap is None or price <= cap]
                    if len(kept) < MIN_JUDGED or sum(kept) < MIN_RIGHT or len(kept) - sum(kept) < MIN_WRONG:
                        continue
                    text = (f"{JOINED[first]} {QUALITIES[second][1][0].format(t=asked)}"
                            + (f" {cap // 10000}만원 이하로" if cap else "") + " 추천해 줘")
                    questions.append({"id": f"P{len(questions) + 1:03d}", "text": text, **base,
                                      "attributes": [first, second], "maxPrice": cap,
                                      "judged": len(kept), "right": sum(kept)})
    PAIR_QUESTIONS.write_text(json.dumps({
        "version": "2026-11-19", "rule": f"right when of the type, within the price and, for both qualities, at least "
        f"{SHARE:.0%} of at least {MIN_ANSWERS} survey answers rate it well; wrong when either is known to fall short",
        "questions": questions}, ensure_ascii=False, indent=1))
    print(len(questions), "questions,", json.dumps(Counter(tuple(q["attributes"]) for q in questions).most_common(8),
                                                   ensure_ascii=False))


def questions_by_id(path: Path | None = None) -> dict[str, dict]:
    files = [path] if path else [QUESTIONS] + [PAIR_QUESTIONS] * PAIR_QUESTIONS.exists()
    return {q["id"]: q for f in files for q in json.loads(f.read_text())["questions"]}


def save(path: Path, rows: list[dict], source: str | None = None) -> None:
    questions = questions_by_id()
    by_attribute: dict[str, Counter] = {}
    total: Counter = Counter()
    for row in rows:
        q = questions[row["id"]]
        row["verdicts"] = [judge(q, i) for i in row["ids"]]
        counts = Counter(row["verdicts"])
        counts.update(slots=5, hit=bool(counts["right"]), questions=1)
        total += counts
        attribute = " + ".join(q["attributes"]) if "attributes" in q else q["attribute"]
        by_attribute[attribute] = by_attribute.get(attribute, Counter()) + counts

    def numbers(c: Counter) -> dict:
        return {"questions": c["questions"], "slots": c["slots"], "right": c["right"], "wrong": c["wrong"],
                "unknown": c["unknown"], "empty": c["slots"] - c["right"] - c["wrong"] - c["unknown"],
                "precisionAt5": round(c["right"] / c["slots"], 4),
                "knownPrecision": round(c["right"] / max(1, c["right"] + c["wrong"]), 4),
                "hitAt5": round(c["hit"] / c["questions"], 4)}
    result = {"source": source, "summary": numbers(total),
              "byAttribute": {a: numbers(c) for a, c in sorted(by_attribute.items())}, "rows": rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps(result["summary"], ensure_ascii=False), flush=True)


async def run(out: Path, path: Path = QUESTIONS) -> None:
    import run_llm
    from agent_service import agent
    from agent_service.llm import LlmError
    from agent_service.main import get_llm
    from agent_service.tools import McpTools

    agent.TRACE_PATH = out.with_suffix(".trace.jsonl")
    llm = get_llm()
    rows = []
    async with McpTools() as tools:
        for q in questions_by_id(path).values():
            recording = run_llm.Recording(tools, True)
            try:
                _, products, _, _, _ = await agent.run_agent(q["text"], llm, recording)
                error = None
            except LlmError as e:
                products, error = [], repr(e)[:200]
            rows.append({"id": q["id"], "searches": recording.searches, "error": error,
                         "ids": [p["productId"] for p in products]})
            print(q["id"], q["text"], rows[-1]["ids"], error or "", flush=True)
            await asyncio.sleep(run_llm.PAUSE_SECONDS)
    save(out, rows)


async def replay(source: Path, out: Path) -> None:
    from agent_service import agent
    from agent_service.tools import McpTools

    rows = []
    async with McpTools() as tools:
        for old in json.loads(source.read_text())["rows"]:
            products = []
            if old["searches"]:
                arguments = {k: v for k, v in old["searches"][-1].items() if k != "limit"}
                products = (await agent.search(tools, arguments, None))["products"]
            rows.append({"id": old["id"], "searches": old["searches"][-1:], "error": None,
                         "ids": [p["productId"] for p in products], "savedIds": old["ids"],
                         "evidence": {p["productId"]: [e["excerpt"] for e in p["evidence"]] for p in products}})
            print(old["id"], rows[-1]["ids"], flush=True)
    save(out, rows, str(source))


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build()
    elif sys.argv[1] == "build-pairs":
        build_pairs()
    elif sys.argv[1] == "run":
        asyncio.run(run(Path(sys.argv[2]), PAIR_QUESTIONS if sys.argv[3:] == ["pairs"] else QUESTIONS))
    else:
        asyncio.run(replay(Path(sys.argv[2]), Path(sys.argv[3])))
