"""규칙·사전으로 출처를 못 찾은 반복 결제를 Claude 에게 추론시킨다.

외부로 보내는 정보는 가맹점명·금액·결제일·주기뿐이다.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
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
후보는 최대 3개, 확신이 없으면 confidence 를 low 로 둔다.

가맹점명: {merchant}
금액: {amount}원
주기: {cycle}
결제일: {dates}
참고 구독료 목록(서비스, 요금제, 가격): {fees}"""


class ClaudeInferer:
    def __init__(self, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    @classmethod
    def from_env(cls):
        """API 키가 없으면 None — LLM 단계를 건너뛴다."""
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        return cls()

    def __call__(self, merchant: str, amount: int, cycle: str, dates: list[str], fees: list) -> list[dict]:
        import anthropic

        fee_lines = [f"{f.service}/{f.plan}/{f.price}{f.currency}" for f in fees]
        prompt = PROMPT.format(
            merchant=merchant, amount=amount, cycle=cycle, dates=", ".join(dates), fees="; ".join(fee_lines)
        )
        try:
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=2000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as e:
            logger.warning("Claude 출처 추론 실패: %s", e)
            return []
        if response.stop_reason != "end_turn":
            logger.warning("Claude 출처 추론 중단: %s", response.stop_reason)
            return []
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)["candidates"]
