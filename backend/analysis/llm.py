"""규칙·사전으로 출처를 못 찾은 반복 결제를 Gemini 에게 추론시킨다.

외부로 보내는 정보는 가맹점명·금액·결제일·주기뿐이다.
Gemini API 무료 등급(Google AI Studio 에서 발급한 키)으로 동작한다.
"""

import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

# 무료 등급에서 쓸 수 있는 모델. .env 의 GEMINI_MODEL 로 바꿀 수 있다.
DEFAULT_MODEL = "gemini-3.8-flash"
# 대시보드 요청 안에서 동기로 부르므로, 응답이 늦으면 포기하고 규칙 기반 결과만 쓴다.
TIMEOUT_MS = int(os.environ.get("GEMINI_TIMEOUT_MS", "20000"))
# 캡처 이미지는 한 번에 수십 줄을 읽어야 해서 더 오래 기다린다. 업로드할 때 한 번만 부른다.
IMAGE_TIMEOUT_MS = 90000
SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["medium", "low"]},
                    "reason": {"type": "string"},
                },
                "required": ["service", "confidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}
PROMPT = """한국 카드 명세서의 반복 결제 한 건이 실제로 어떤 서비스인지 추정하라.
가맹점명은 결제대행사(PG사)나 앱마켓 표기일 수 있다. 근거가 약하면 후보를 비워 둬라.
앱마켓(app_store, google_play) 결제는 수수료 때문에 웹 가격보다 비쌀 수 있다. 공유 대행사(share) 결제는 원가를 여러 명이 나눈 1인분이다.
후보는 최대 3개, 확신이 없으면 confidence 를 low 로 둔다.

가맹점명: {merchant}
금액: {amount}원
주기: {cycle}
결제일: {dates}
참고 구독료 목록(서비스/요금제/가격/결제경로): {fees}"""


STATEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "merchant": {"type": "string"},
                    "amount": {"type": "integer", "description": "원 단위. 출금·결제는 양수, 입금은 음수"},
                },
                "required": ["date", "merchant", "amount"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["transactions"],
    "additionalProperties": False,
}
STATEMENT_PROMPT = """은행·카드 앱의 거래내역 화면 캡처다. 화면에 보이는 거래를 한 줄도 빠짐없이 옮겨라.
- date: YYYY-MM-DD. 화면의 월·연도 머리글로 연도를 정하고, 연도가 안 보이면 {today} 이전의 가장 가까운 날짜로 둔다.
- merchant: 가맹점명·받는 사람 표기를 화면 그대로 (번역·보정하지 말 것).
- amount: 출금·결제는 양수, 입금(+ 표시, 파란 글씨 등)은 음수. 잔액 숫자는 무시한다.
거래 목록이 아닌 이미지면 transactions 를 빈 배열로 둔다."""


def _api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _client(timeout_ms: int):
    from google import genai

    return genai.Client(api_key=_api_key(), http_options={"timeout": timeout_ms, "retry_options": {"attempts": 1}})


def _model() -> str:
    return os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL


def _generate_json(client, model: str, input, schema: dict, max_tokens: int, task: str) -> dict | None:
    """JSON 응답을 dict 로. 실패하면 None — 호출한 쪽이 규칙 기반 결과로 계속 진행한다."""
    try:
        interaction = client.interactions.create(
            model=model,
            input=input,
            generation_config={"thinking_level": "low", "max_output_tokens": max_tokens},
            response_format={"type": "text", "mime_type": "application/json", "schema": schema},
        )
    except Exception as e:  # noqa: BLE001
        # Interactions API 의 예외는 google.genai.errors 와 계층이 달라 공개 import 경로가 없다.
        # 무료 등급 한도 초과(429)·타임아웃·네트워크 오류 모두 여기로 온다.
        logger.warning("Gemini %s 실패: %s", task, e)
        return None
    if interaction.status != "completed" or not interaction.output_text:
        logger.warning("Gemini %s 중단: %s", task, interaction.status)
        return None
    try:
        return json.loads(interaction.output_text)
    except json.JSONDecodeError as e:
        logger.warning("Gemini %s 응답 파싱 실패: %s", task, e)
        return None


class GeminiInferer:
    # 대시보드를 열 때마다 분석을 다시 돌리므로, 같은 반복 결제는 서버가 켜져 있는 동안 한 번만 묻는다.
    _cache: dict[tuple, list[dict]] = {}

    def __init__(self, client=None, model: str | None = None):
        self.client = client or _client(TIMEOUT_MS)
        self.model = model or _model()

    @classmethod
    def from_env(cls):
        """API 키가 없으면 None — LLM 단계를 건너뛴다."""
        if not _api_key():
            return None
        return cls()

    def __call__(self, merchant: str, amount: int, cycle: str, dates: list[str], fees: list) -> list[dict]:
        key = (self.model, merchant, amount, cycle, tuple(dates))
        if key in self._cache:
            return self._cache[key]
        fee_lines = [f"{f.service}/{f.plan}/{f.price}{f.currency}/{f.route or 'web'}" for f in fees]
        prompt = PROMPT.format(
            merchant=merchant, amount=amount, cycle=cycle, dates=", ".join(dates), fees="; ".join(fee_lines)
        )
        result = _generate_json(self.client, self.model, prompt, SCHEMA, 2000, "출처 추론")
        try:
            candidates = result["candidates"][:3]
        except (KeyError, TypeError):
            return []  # 실패는 캐시하지 않는다 — 다음 요청에서 다시 시도
        self._cache[key] = candidates
        return candidates


class GeminiStatementReader:
    """은행·카드앱 캡처 이미지에서 거래 목록을 읽는다. 이미지 전체가 Gemini 로 전송된다."""

    def __init__(self, client=None, model: str | None = None):
        self.client = client or _client(IMAGE_TIMEOUT_MS)
        self.model = model or _model()

    @classmethod
    def from_env(cls):
        if not _api_key():
            return None
        return cls()

    def __call__(self, data: bytes, mime_type: str) -> list[dict] | None:
        """[{"date", "merchant", "amount"}] — amount 는 지출이 양수. 읽지 못하면 None."""
        from datetime import date

        content = [
            {"type": "text", "text": STATEMENT_PROMPT.format(today=date.today().isoformat())},
            {"type": "image", "data": base64.b64encode(data).decode(), "mime_type": mime_type},
        ]
        result = _generate_json(self.client, self.model, content, STATEMENT_SCHEMA, 16000, "캡처 이미지 판독")
        try:
            return list(result["transactions"])
        except (KeyError, TypeError):
            return None
