"""카드사 앱 결제 알림을 공통 스키마(Transaction)로 바꾼다.

안드로이드 앱이 카드사 앱의 푸시 알림(제목·본문·수신 시각)을 보내 오면 승인 건만 거래로 만든다.
카드사마다 문구가 달라 FORMATS 에 정규식으로 등록한다. 카드번호·이름·누적금액은 읽지 않는다.

예: "[데모카드] 승인 본인3381 14,900원 일시불 10/15 14:22 토스페이먼츠 누적1,234,000원"
"""

import re
from datetime import date, datetime

from .parsers import Transaction

# 승인 알림의 공통 뼈대: 금액 ... 월/일 시:분 가맹점 [누적...]
FORMATS = {
    "demo_card": re.compile(
        r"승인\s.*?(?P<amount>[\d,]+)원.*?"
        r"(?P<month>\d{1,2})/(?P<day>\d{1,2})\s+\d{1,2}:\d{2}\s+"
        r"(?P<merchant>.+?)(?:\s+누적.*)?$"
    ),
}
CANCEL_WORDS = ("취소", "거절", "승인거절")


def parse_notification(title: str, text: str, posted_at: datetime) -> Transaction | None:
    """승인 알림이면 Transaction, 취소·광고·기타 알림이면 None."""
    body = re.sub(r"\s+", " ", f"{title} {text}").strip()
    if any(word in body for word in CANCEL_WORDS):
        return None
    for pattern in FORMATS.values():
        m = pattern.search(body)
        if m:
            merchant = m["merchant"].strip()
            amount = int(m["amount"].replace(",", ""))
            if not merchant or amount <= 0:
                return None
            try:
                charged = _charge_date(int(m["month"]), int(m["day"]), posted_at.date())
            except ValueError:
                return None
            return Transaction(date=charged, merchant=merchant, amount=amount)
    return None


def _charge_date(month: int, day: int, received: date) -> date:
    """알림에는 연도가 없다. 수신일보다 미래가 되면 작년 결제로 본다 (12/31 결제가 1/1 에 도착)."""
    charged = date(received.year, month, day)
    return charged if charged <= received else date(received.year - 1, month, day)
