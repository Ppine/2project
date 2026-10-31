"""돈구마 MCP 서버 (stdio).

에이전트(Claude Desktop 등)가 사용자 대신 구독과 결제 출처를 조회한다.
데이터는 REST API 에서 사용자가 발급한 읽기 전용 토큰으로 가져온다.

환경변수:
    DONGGUMA_API_URL  기본 http://127.0.0.1:8000/api
    DONGGUMA_TOKEN    `python manage.py issue_token` 으로 발급한 토큰
"""

import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

API_URL = os.environ.get("DONGGUMA_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
TOKEN_ERROR = "서비스 연결 토큰이 유효하지 않습니다. 토큰 확인이 필요합니다."
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

server = MCPServer(
    name="dongguma",
    title="돈구마",
    instructions=(
        "사용자의 카드 결제 내역(명세서·카드사 결제 알림)에서 구독과 정체불명 결제를 조회하는 읽기 전용 도구다. "
        "출처 추적 결과는 단정이 아니라 후보와 신뢰도(high/medium/low)이므로, "
        "신뢰도가 high 가 아니면 사용자에게 확인을 구하라. "
        "해지를 원하면 구독의 cancel.url 을 안내하라. 이 도구로 해지를 실행하지는 않는다."
    ),
)


def _get(path: str, params: dict | None = None) -> dict[str, Any]:
    token = os.environ.get("DONGGUMA_TOKEN", "")
    if not token:
        raise ToolError(TOKEN_ERROR)
    try:
        response = httpx.get(
            f"{API_URL}{path}", params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30
        )
    except httpx.HTTPError as e:
        raise ToolError(f"돈구마 서버에 연결할 수 없습니다: {e}") from e

    if response.status_code == 401:
        raise ToolError(TOKEN_ERROR)
    body = response.json()
    if response.status_code >= 400:
        raise ToolError(body.get("detail", f"요청 실패 ({response.status_code})"))
    return body


@server.tool(annotations=READ_ONLY)
def list_subscriptions() -> dict[str, Any]:
    """사용자가 구독 중인 서비스 목록과 월 합계를 돌려준다.

    각 구독: service, plan, amount(원), cycle(monthly/yearly), monthly_amount,
    next_payment_date, confidence, candidates, evidence, price_history(금액 변동 이력),
    cancel(서비스가 확정된 구독의 해지 관리 화면: via=web/google_play/app_store, url. 미확정이면 null).
    monthly_total 은 모든 구독의 월 환산 합계(원)다.
    """
    return _get("/subscriptions/")


@server.tool(annotations=READ_ONLY)
def explain_charge(merchant: str, amount: int) -> dict[str, Any]:
    """명세서의 결제 한 건이 실제로 어떤 서비스인지 추적한다.

    merchant: 명세서에 찍힌 가맹점명 (예: "토스페이먼츠", "APPLE.COM/BILL")
    amount: 결제 금액(원, 정수)

    is_subscription 이 false 면 반복 결제가 아니므로 구독으로 단정하지 말 것.
    candidates 는 서비스 후보와 신뢰도, evidence 는 판단 근거다.
    """
    return _get("/charges/explain/", {"merchant": merchant, "amount": amount})


if __name__ == "__main__":
    server.run()
