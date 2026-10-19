"""Quality of the LLM path with and without category/brand filters (ADR-95).

uv run --package agent-service python eval/run_llm.py nofilter filter > .local/eval/llm.txt
uv run --package agent-service python eval/run_llm.py rescore nofilter filter   # after judging new products

Each question runs RUNS times per variant because the LLM is not deterministic. "nofilter" hides category and brand
from the tool schema and the system prompt, so the two variants differ only in the filters.
"""

import asyncio
import copy
import json
import statistics
import sys
from pathlib import Path

from agent_service import agent
from agent_service.llm import LlmError
from agent_service.main import get_llm
from agent_service.tools import McpTools

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pool import ROOT, hard_violation, sql  # noqa: E402

RUNS = 3
FILTERS = ("category", "brand")
FILTER_LINE = next(line for line in agent.SYSTEM_PROMPT.splitlines() if "category" in line)


class Recording:
    """McpTools as the agent sees it, recording search arguments and optionally hiding the filters."""

    def __init__(self, tools: McpTools, filters: bool) -> None:
        self.tools = tools
        self.filters = filters
        self.searches: list[dict] = []
        self.definitions = copy.deepcopy(tools.definitions)
        if not filters:
            for definition in self.definitions:
                for name in FILTERS:
                    definition["function"]["parameters"]["properties"].pop(name, None)

    async def call(self, name: str, arguments: dict) -> dict:
        if name == "search_products":
            if not self.filters:
                arguments = {k: v for k, v in arguments.items() if k not in FILTERS}
            self.searches.append(arguments)
        return await self.tools.call(name, arguments)


def score(q: dict, judgment: dict, products: list[dict]) -> dict:
    ids = [p["productId"] for p in products]
    violations = {}
    for p in products:
        info = {"category": sql(f"select category_code from products where id = {p['productId']}"),
                "price": p["price"], "brand": p["brand"]}
        v = hard_violation(q, info)
        if v:
            violations[p["productId"]] = v
    judged = judgment["relevant"].keys() | judgment["notRelevant"].keys()
    return {"ids": ids, "relevant": [i for i in ids if str(i) in judgment["relevant"]], "violations": violations,
            "unjudged": [i for i in ids if str(i) not in judged and i not in violations]}


async def run(variant: str, questions: list[dict], judgments: dict, tools: McpTools) -> list[dict]:
    llm = get_llm()
    agent.SYSTEM_PROMPT = PROMPT if variant == "filter" else PROMPT.replace(FILTER_LINE + "\n", "")
    rows = []
    for attempt in range(RUNS):
        for q in questions:
            recording = Recording(tools, variant == "filter")
            try:
                _, products, _, _ = await agent.run_agent(q["text"], llm, recording)
                error = None
            except LlmError as e:
                products, error = [], repr(e)[:200]
            row = {"variant": variant, "run": attempt, "id": q["id"], "searches": recording.searches,
                   "error": error, **score(q, judgments[q["id"]], products)}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    return rows


def summary(rows: list[dict]) -> dict:
    by_run = {}
    for r in rows:
        by_run.setdefault(r["run"], []).append(r)
    runs = []
    for group in by_run.values():
        shown = sum(len(r["ids"]) for r in group)
        runs.append({"hitAt5": sum(1 for r in group if r["relevant"]) / len(group),
                     "relevantInTop5Mean": statistics.mean(len(r["relevant"]) for r in group),
                     "violationRate": sum(len(r["violations"]) for r in group) / shown if shown else 0,
                     "shown": shown, "errors": sum(1 for r in group if r["error"]),
                     "unjudged": sum(len(r["unjudged"]) for r in group)})
    return {"runs": runs, "hitAt5Mean": statistics.mean(r["hitAt5"] for r in runs),
            "relevantInTop5MeanMean": statistics.mean(r["relevantInTop5Mean"] for r in runs)}


PROMPT = agent.SYSTEM_PROMPT


def rescore(variant: str, judgments: dict) -> None:
    """Score saved results again after unjudged products were judged, without calling the LLM."""
    path = ROOT / f".local/eval/llm-{variant}.json"
    result = json.loads(path.read_text())
    for row in result["rows"]:
        judgment = judgments[row["id"]]
        judged = judgment["relevant"].keys() | judgment["notRelevant"].keys()
        violations = {int(k) for k in row["violations"]}
        row["relevant"] = [i for i in row["ids"] if str(i) in judgment["relevant"]]
        row["unjudged"] = [i for i in row["ids"] if str(i) not in judged and i not in violations]
    result["summary"] = summary(result["rows"])
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({"variant": variant, **result["summary"]}, ensure_ascii=False))


async def main() -> None:
    questions = json.loads((ROOT / "eval/quality-questions.json").read_text())["questions"]
    judgments = json.loads((ROOT / "eval/quality-judgments.json").read_text())["judgments"]
    if sys.argv[1] == "rescore":
        for variant in sys.argv[2:]:
            rescore(variant, judgments)
        return
    agent.TRACE_PATH = ROOT / ".local/eval/llm-trace.jsonl"
    async with McpTools() as tools:
        for variant in sys.argv[1:]:
            rows = await run(variant, questions, judgments, tools)
            result = {"variant": variant, "summary": summary(rows), "rows": rows}
            (ROOT / f".local/eval/llm-{variant}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
            print(json.dumps({"variant": variant, **result["summary"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
