"""Judge whether the reviews an answer cites as evidence say what the question asked (ADR-173).

ANTHROPIC_API_KEY=... uv run --with anthropic python eval/evidence.py <trace.jsonl> <judgments.json>   # needs catalog-db

The trace holds one chat per line with its question ("message") and, per recommended product, the reviews the card
cites ("reasons"). Each (question, review) pair is judged once by a model other than the one that wrote the answer,
reading the whole review, and kept in judgments.json: a later run judges only the pairs it has not seen, so the same
review keeps its label when two runs are compared. The model's sampling cannot be pinned, which is why labels are kept.

RULES and CONDITIONS were written before any review was judged. Only the 21 questions of quality-questions.json have
conditions; chats with other questions are skipped.
"""
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from build_pool import sql

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-sonnet-5-5"
LABELS = {"same": "같은 방향", "opposite": "반대 방향", "unrelated": "무관"}
SKIN = {"dry": "건성", "oily": "지성", "combination": "복합성", "sensitive": "민감성", "dehydrated_oily": "수부지",
        "normal": "중성", "trouble_prone": "트러블성"}

# What a review can say about each question. Type, price, brand, ingredients and popularity are checked by code.
CONDITIONS = {
    "Q01": ["건성 피부에 맞는다 (촉촉하다, 건조하지 않다)", "끈적이지 않는다 (산뜻하다, 가볍다)"],
    "Q02": ["진정된다 (붉은기, 열감, 자극이 가라앉는다)"],
    "Q03": ["산뜻하다 (가볍다, 번들거리지 않는다)", "지성 피부에 맞는다"],
    "Q04": ["자극이 없다 (따갑지 않다, 순하다)", "예민한 피부에 맞는다"],
    "Q05": ["트러블 피부에 맞는다 (트러블이 가라앉는다, 트러블이 나지 않는다)"],
    "Q06": ["백탁이 없다", "촉촉하다 (건조하지 않다)"],
    "Q07": ["입술이 촉촉해진다 (트는 것, 각질이 줄어든다)"],
    "Q08": ["자극이 없다 (순하다, 세안 뒤 당기지 않는다)"],
    "Q09": ["손상모에 좋다 (머릿결이 부드러워진다, 푸석함과 갈라짐이 줄어든다)"],
    "Q10": ["진정된다 (붉은기, 열감이 가라앉는다)"],
    "Q11": ["각질이 정리된다 (피부결이 매끈해진다)"],
    "Q12": ["보습이 된다 (촉촉하다, 당기지 않는다)", "건성 피부에 맞는다"],
    "Q13": ["수분감이 좋다 (촉촉하다)"],
    "Q14": ["미백 효과가 있다 (톤이 밝아진다, 잡티가 옅어진다)"],
    "Q15": ["향이 오래간다"],
    "Q16": ["향이 없다 (거의 없다)", "보습이 된다 (촉촉하다)"],
    "Q17": ["자극이 없다 (순하다, 따갑지 않다, 알코올 느낌이 없다)"],
    "Q18": ["향이 없다 (거의 없다)"],
    "Q19": ["자극이 없다 (순하다, 따갑지 않다)", "예민한 피부에 맞는다"],
    "Q20": ["잘 지워진다", "자극이 없다 (순하다)"],
    "Q21": ["자극이 없다 (순하다)", "향이 없다 (거의 없다)"],
}

RULES = """상품 추천 답이 근거로 보여 준 리뷰 한 개가, 질문이 물은 조건을 어떻게 말하는지 판정한다.
리뷰 전체를 읽고 셋 중 하나를 고른다.

- same (같은 방향): 써 본 경험으로, 조건 중 하나 이상이 맞다고 말한다. 그리고 어느 조건도 아니라고 말하지 않는다.
- opposite (반대 방향): 조건 중 하나라도 아니라고 말한다. 다른 조건을 좋게 말했어도 반대 방향이다.
- unrelated (무관): 어느 조건도 말하지 않는다.

세부 규칙
1. 조건 옆 괄호 안의 표현이나 같은 뜻의 말이면 그 조건을 말한 것이다. 조건에 없는 품질(예: 발림성, 용기, 가성비)만 말하면 무관이다.
2. 조건마다 리뷰가 내린 결론을 본다. "살짝 끈적이지만 금방 흡수돼서 괜찮다"는 끈적임이 문제없다는 결론이라 같은 방향이고, "끈적여서 여름엔 못 쓰겠다"는 반대 방향이다. "처음엔 촉촉한데 금방 건조해진다"는 반대 방향이다.
3. 배송, 가격, 포장, "좋아요", "재구매"만 있는 리뷰는 무관이다. 아직 안 써 봤거나 기대만 쓴 리뷰, 선물이라 써 보지 않은 리뷰도 무관이다.
4. 작성자 피부 타입 칸만으로는 같은 방향이 아니다. 글이 조건을 말해야 한다. 다만 질문이 물은 피부 타입의 작성자가 자기 피부에 잘 맞는다고 쓰면 그 피부 타입 조건을 말한 것이다.
5. 별점은 참고만 한다. 별점 5점이어도 조건을 아니라고 말하면 반대 방향이고, 별점이 낮아도 조건이 맞다고 말하면 같은 방향이다.
6. 상품 종류, 가격, 브랜드, 성분, 인기는 판정하지 않는다.

reason에는 판정의 근거가 된 리뷰 구절을 한 문장으로 쓴다."""

SCHEMA = {"type": "object",
          "properties": {"reason": {"type": "string"}, "label": {"type": "string", "enum": list(LABELS)}},
          "required": ["reason", "label"], "additionalProperties": False}


def card(question: dict, review: dict) -> str:
    """What the judge reads, and what the page for the human check shows.

    >>> print(card({"id": "Q15", "text": "향이 오래가는 바디로션"}, {"grade": 4, "skinType": None, "content": "향 좋아요"}))
    질문: 향이 오래가는 바디로션
    리뷰로 확인할 조건:
    - 향이 오래간다
    리뷰 (별점 4점, 작성자 피부 타입 없음):
    향 좋아요
    """
    conditions = "\n".join(f"- {c}" for c in CONDITIONS[question["id"]])
    return (f"질문: {question['text']}\n리뷰로 확인할 조건:\n{conditions}\n"
            f"리뷰 (별점 {review['grade']}점, 작성자 피부 타입 {SKIN.get(review['skinType'], '없음')}):\n{review['content']}")


def reviews(ids: list[int]) -> dict[int, dict]:
    rows = sql("select json_agg(json_build_object('id', id, 'grade', grade, 'skinType', skin_type, 'content', content)) "
               f"from reviews where id in ({','.join(map(str, ids))})")
    return {r["id"]: r for r in json.loads(rows)}


def judge(client, question: dict, review: dict) -> dict:
    response = client.messages.create(
        model=MODEL, max_tokens=4000, system=RULES, messages=[{"role": "user", "content": card(question, review)}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def judge_all(pairs: list[tuple[str, int]], store: Path) -> dict[str, dict]:
    """Judges the pairs the store does not hold yet and returns the whole store."""
    import anthropic

    questions = {q["id"]: q for q in json.loads((ROOT / "eval/quality-questions.json").read_text())["questions"]}
    judgments = json.loads(store.read_text()) if store.exists() else {}
    todo = sorted({p for p in pairs if f"{p[0]}:{p[1]}" not in judgments})
    if todo:
        found = reviews([review_id for _, review_id in todo])
        client = anthropic.Anthropic()
        with ThreadPoolExecutor(8) as pool:
            done = pool.map(lambda p: judge(client, questions[p[0]], found[p[1]]), todo)
            for (qid, review_id), judgment in zip(todo, done):
                judgments[f"{qid}:{review_id}"] = judgment
        store.write_text(json.dumps(judgments, ensure_ascii=False, indent=1))
    return judgments


def cited(trace: Path) -> list[tuple[str, list[int]]]:
    """Per recommended product of every chat with a known question: the question id and the review ids its card cites."""
    ids = {q["text"]: q["id"] for q in json.loads((ROOT / "eval/quality-questions.json").read_text())["questions"]}
    return [(ids[chat["message"]], [e["reviewId"] for e in product["evidence"]])
            for chat in map(json.loads, trace.read_text().splitlines()) if chat["message"] in ids
            for product in chat["reasons"].values()]


def summary(cards: list[tuple[str, list[int]]], judgments: dict[str, dict]) -> dict:
    """
    >>> j = {"Q01:1": {"label": "same"}, "Q01:2": {"label": "unrelated"}, "Q01:3": {"label": "opposite"}}
    >>> summary([("Q01", [1, 2]), ("Q01", [3]), ("Q01", [])], j)
    {'cards': 3, 'reviews': 3, 'same': 1, 'opposite': 1, 'unrelated': 1, 'cardsWithSame': 1, 'cardsWithOpposite': 1}
    """
    labels = [[judgments[f"{qid}:{i}"]["label"] for i in review_ids] for qid, review_ids in cards]
    count = Counter(label for card_labels in labels for label in card_labels)
    return {"cards": len(cards), "reviews": sum(count.values()), **{label: count[label] for label in LABELS},
            "cardsWithSame": sum("same" in c for c in labels), "cardsWithOpposite": sum("opposite" in c for c in labels)}


if __name__ == "__main__":
    cards = cited(Path(sys.argv[1]))
    judged = judge_all([(qid, i) for qid, review_ids in cards for i in review_ids], Path(sys.argv[2]))
    print(json.dumps(summary(cards, judged), ensure_ascii=False))
