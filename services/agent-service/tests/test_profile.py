"""Focused profile API tests with a fake LLM; no external service is needed."""

import json
import unittest

from fastapi.testclient import TestClient

from agent_service.llm import LlmError
from agent_service.main import app, get_llm


class FakeLlm:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append((messages, tools))
        return {"content": self.content}, {}


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def post(self, **overrides):
        body = {"skinType": "dry", "skinNotes": "겨울에는 건조해요", "conversations": [
            {"id": "c1", "question": "크림 A가 잘 맞았는데 비슷한 크림 추천해 줘", "answer": "제품 B를 추천합니다"}]}
        body.update(overrides)
        return self.client.post("/api/v1/profile/insights", json=body)

    def test_근거가_있는_관찰만_반환한다(self):
        fake = FakeLlm(json.dumps({"observations": [
            {"text": "겨울철 건조함을 직접 언급했어요", "sourceIds": ["profile"]}],
            "matchedProducts": [{"name": "크림 A", "sourceIds": ["c1"]}],
            "matchedIngredients": []}))
        app.dependency_overrides[get_llm] = lambda: fake
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["observations"][0]["sourceIds"], ["profile"])
        self.assertEqual(response.json()["matchedProducts"][0]["name"], "크림 A")
        self.assertEqual(fake.calls[0][1], [])

    def test_없는_근거_id는_거부한다(self):
        app.dependency_overrides[get_llm] = lambda: FakeLlm(
            '{"observations":[{"text":"근거 없음","sourceIds":["missing"]}]}')
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "PROFILE_ANALYSIS_UNAVAILABLE")

    def test_AI_답변에만_나온_제품은_적합_제품으로_받지_않는다(self):
        app.dependency_overrides[get_llm] = lambda: FakeLlm(
            '{"observations":[],"matchedProducts":[{"name":"제품 B","sourceIds":["c1"]}],"matchedIngredients":[]}')
        response = self.post()
        self.assertEqual(response.status_code, 503)

    def test_코드_블록으로_감싼_답과_상한을_넘은_관찰도_받는다(self):
        observations = [{"text": f"관찰 {n}", "sourceIds": ["profile"]} for n in range(7)]
        content = "```json\n" + json.dumps({"observations": observations, "matchedProducts": [],
                                             "matchedIngredients": []}, ensure_ascii=False) + "\n```"
        app.dependency_overrides[get_llm] = lambda: FakeLlm(content)
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([o["text"] for o in response.json()["observations"]], [f"관찰 {n}" for n in range(5)])

    def test_키가_없으면_503이다(self):
        app.dependency_overrides[get_llm] = lambda: None
        self.assertEqual(self.post().status_code, 503)

    def test_입력_제한을_검사한다(self):
        app.dependency_overrides[get_llm] = lambda: FakeLlm('{"observations":[]}')
        response = self.post(skinNotes="x" * 501)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_PROFILE_REQUEST")
