from datetime import date, datetime

import pytest

from analysis.notifications import parse_notification

RECEIVED = datetime(2026, 10, 15, 14, 23)


def test_parse_approval():
    tx = parse_notification("[데모카드] 승인", "본인3381 14,900원 일시불 10/15 14:22 토스페이먼츠 누적1,234,000원",
                            RECEIVED)
    assert (tx.date, tx.merchant, tx.amount) == (date(2026, 10, 15), "토스페이먼츠", 14900)
    assert "3381" not in repr(tx)


def test_parse_without_accumulated_total():
    tx = parse_notification("[데모카드] 승인", "본인3381 29,000원 일시불 10/14 09:01 GOOGLE*SPEAK", RECEIVED)
    assert (tx.merchant, tx.amount) == ("GOOGLE*SPEAK", 29000)


def test_year_rolls_back_for_late_notification():
    tx = parse_notification("[데모카드] 승인", "본인3381 4,900원 일시불 12/31 23:59 네이버플러스멤버십",
                            datetime(2027, 1, 1, 0, 1))
    assert tx.date == date(2026, 12, 31)


@pytest.mark.parametrize(
    "title, text",
    [
        ("[데모카드] 승인취소", "본인3381 14,900원 10/15 14:22 토스페이먼츠"),
        ("[데모카드] 이벤트", "10월 캐시백 혜택을 확인하세요"),
        ("[데모카드] 승인", "본인3381 14,900원 일시불 02/30 14:22 토스페이먼츠"),
    ],
)
def test_ignores_non_charges(title, text):
    assert parse_notification(title, text, RECEIVED) is None
