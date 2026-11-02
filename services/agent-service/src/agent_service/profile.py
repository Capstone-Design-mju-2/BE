"""Opt-in, stateless cosmetic profile insights from user-provided history."""

import json
from typing import Literal

from pydantic import BaseModel, Field

from agent_service.llm import Llm, LlmError


class Conversation(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=2000)


class ProfileRequest(BaseModel):
    skin_type: Literal["dry", "oily", "combination", "sensitive"] | None = Field(default=None, alias="skinType")
    skin_notes: str = Field(default="", max_length=500, alias="skinNotes")
    conversations: list[Conversation] = Field(default_factory=list, max_length=20)


class Observation(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    source_ids: list[str] = Field(min_length=1, max_length=5, alias="sourceIds")


class MatchedItem(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source_ids: list[str] = Field(min_length=1, max_length=5, alias="sourceIds")


class ProfileInsights(BaseModel):
    observations: list[Observation] = Field(max_length=5)
    matched_products: list[MatchedItem] = Field(default_factory=list, max_length=10, alias="matchedProducts")
    matched_ingredients: list[MatchedItem] = Field(default_factory=list, max_length=10, alias="matchedIngredients")


SYSTEM = """당신은 화장품 상담 기록 요약 도우미입니다. JSON 객체만 출력하세요.
형식: {"observations":[{"text":"한국어로 짧은 피부 특성/선호 관찰","sourceIds":["대화 ID 또는 profile"]}],"matchedProducts":[{"name":"제품명","sourceIds":["대화 ID"]}],"matchedIngredients":[{"name":"성분명","sourceIds":["대화 ID"]}]}
사용자가 직접 적은 피부 타입과 메모 또는 질문에 명시된 경험만 근거로 쓰세요.
AI가 과거에 추천한 제품/성분이나 AI 답변을 사용자의 사용 경험으로 취급하지 마세요.
matchedProducts, matchedIngredients는 사용자 질문이나 메모에 실제 사용 후 잘 맞았다고 직접 말한 경우에만 채우세요. 추천받았다는 사실만으로 채우지 마세요.
근거가 없는 피부 타입, 효과, 알레르기, 적합 제품/성분을 추측하지 마세요.
진단이나 치료 조언을 하지 마세요. 확실한 근거가 없으면 observations를 빈 배열로 반환하세요.
각 문장의 sourceIds에는 실제로 사용한 대화 ID 또는 피부 타입/메모를 뜻하는 profile만 넣으세요."""


async def analyze_profile(request: ProfileRequest, llm: Llm) -> ProfileInsights:
    evidence = {item.id for item in request.conversations}
    if request.skin_type or request.skin_notes.strip():
        evidence.add("profile")
    if not evidence:
        return ProfileInsights(observations=[], matchedProducts=[], matchedIngredients=[])

    payload = {
        "skinType": request.skin_type,
        "skinNotes": request.skin_notes,
        "conversations": [item.model_dump() for item in request.conversations],
    }
    message, _ = await llm.complete([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], tools=[])
    try:
        content = message["content"]
        if not isinstance(content, str):
            raise ValueError("missing text")
        result = ProfileInsights.model_validate_json(content)
        items = result.observations + result.matched_products + result.matched_ingredients
        if any(not set(item.source_ids).issubset(evidence) for item in items):
            raise ValueError("unknown evidence id")
        return result
    except (KeyError, TypeError, ValueError) as error:
        raise LlmError("profile response was invalid") from error
