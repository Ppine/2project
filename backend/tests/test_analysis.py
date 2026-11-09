import csv
from datetime import date, timedelta

import pytest

from analysis.clean import describe_merchant
from analysis.detect import add_months, detect_subscriptions
from analysis.infer import analyze, explain_charge
from analysis.parsers import Transaction, UnsupportedFormat, parse_statement

from .conftest import LABELS_CSV


def _labels():
    with open(LABELS_CSV, encoding="utf-8") as f:
        return {row["승인번호"]: row for row in csv.DictReader(f)}


# --- 파서 ---


def test_parser_drops_card_number(demo_transactions):
    assert len(demo_transactions) > 100
    assert all("9410" not in repr(t) for t in demo_transactions)


@pytest.mark.parametrize(
    "filename, data",
    [
        ("sample.pdf", b"%PDF-1.4"),
        ("missing_amount.csv", "이용일자,가맹점명,승인번호\n2026-05-01,GS25,1\n".encode()),
        ("empty.csv", "이용일자,가맹점명,이용금액\n".encode()),
        ("bad_amount.csv", "이용일자,가맹점명,이용금액\n2026-05-01,GS25,abc\n".encode()),
    ],
)
def test_parser_rejects_unsupported(filename, data):
    with pytest.raises(UnsupportedFormat) as e:
        parse_statement(filename, data)
    assert str(e.value) == "지원하지 않는 명세서 형식입니다"


def test_parser_reads_cp949():
    data = "이용일자,가맹점명,이용금액\n2026.05.01,토스페이먼츠,\"14,900원\"\n".encode("cp949")
    assert parse_statement("a.csv", data) == [Transaction(date(2026, 5, 1), "토스페이먼츠", 14900)]


# --- 가맹점 정제 ---


@pytest.mark.parametrize(
    "raw, intermediary, channel, hint",
    [
        ("토스페이먼츠(주)", "토스페이먼츠", "pg", None),
        ("PAYPAL *SPOTIFY", "PayPal", "pg", "SPOTIFY"),
        ("APPLE.COM/BILL", "APPLE.COM/BILL", "apple", None),
        ("GOOGLE*SPEAK", "GOOGLE", "google", "SPEAK"),
        ("NETFLIX.COM", None, None, None),
    ],
)
def test_describe_merchant(raw, intermediary, channel, hint):
    info = describe_merchant(raw)
    assert (info.intermediary, info.channel, info.hint) == (intermediary, channel, hint)


# --- 반복 결제 탐지 (정답 라벨 기준) ---


def test_detects_exactly_labeled_subscriptions(demo_transactions):
    labels = _labels()
    detected = {tx.approval_no for sub in detect_subscriptions(demo_transactions) for tx in sub.charges}
    expected = {no for no, row in labels.items() if row["구독여부"] == "Y"}
    assert detected == expected  # 정밀도·재현율 1.0


def test_subscription_services_match_labels(demo_transactions, fees):
    labels = _labels()
    result = analyze(demo_transactions, fees)
    assert len(result["subscriptions"]) == 8
    for sub in result["subscriptions"]:
        services = {labels[tx]["서비스"] for tx in _approvals(demo_transactions, sub)}
        assert len(services) == 1
        assert services.pop() in [c["service"] for c in sub["candidates"]]


def _approvals(transactions, sub):
    return [t.approval_no for t in transactions if t.merchant == sub["merchant"] and t.amount in
            {h["amount"] for h in sub["price_history"]}]


def test_price_increase_merged_into_one_subscription(demo_transactions, fees):
    netflix = next(s for s in analyze(demo_transactions, fees)["subscriptions"] if s["service"] == "Netflix")
    assert [h["amount"] for h in netflix["price_history"]] == [13500, 17000]
    assert netflix["amount"] == 17000
    assert netflix["charge_count"] == 6


def test_monthly_total_and_next_dates(demo_transactions, fees):
    result = analyze(demo_transactions, fees)
    assert result["monthly_total"] == 14900 + 17000 + 11990 + 4400 + 7890 + 9900 + 29000 + 4900
    youtube = next(s for s in result["subscriptions"] if s["service"] == "YouTube Premium")
    assert youtube["next_payment_date"] == "2026-11-15"


def test_add_months_clamps_day():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


# --- 출처 추적 (UAT 시나리오 2) ---


def test_explain_toss_14900_is_youtube_premium(demo_transactions, fees):
    result = explain_charge("토스페이먼츠", 14900, demo_transactions, fees)
    assert result["is_subscription"] is True
    assert result["confidence"] == "high"
    assert [c["service"] for c in result["candidates"]] == ["YouTube Premium"]
    assert any("14,900" in e for e in result["evidence"])
    assert any("매월" in e for e in result["evidence"])


def test_explain_kg_inicis_one_off_is_not_subscription(demo_transactions, fees):
    result = explain_charge("KG이니시스", 23170, demo_transactions, fees)
    assert result["found"] is True
    assert result["is_subscription"] is False
    assert result["confidence"] == "low"
    assert result["candidates"] == []


def test_explain_ambiguous_price_is_medium(demo_transactions, fees):
    result = explain_charge("NICE페이", 9900, demo_transactions, fees)
    assert result["confidence"] == "medium"
    assert {"Disney+", "Canva", "CapCut"} <= {c["service"] for c in result["candidates"]}


def test_explain_unknown_charge(demo_transactions, fees):
    assert explain_charge("없는가맹점", 1000, demo_transactions, fees)["found"] is False


def test_user_alias_wins(demo_transactions, fees):
    result = explain_charge("NICE페이", 9900, demo_transactions, fees, aliases={"NICE페이": "Disney+"})
    assert result["confidence"] == "high"
    assert result["candidates"][0]["service"] == "Disney+"


def test_llm_used_only_when_rules_fail(fees):
    txs = [Transaction(date(2026, m, 5), "KCP 알수없는상점", 7777) for m in (5, 6, 7)]
    calls = []

    def fake_llm(merchant, amount, cycle, dates, fees):
        calls.append(merchant)
        return [{"service": "Mystery", "confidence": "low", "reason": "추정"}]

    result = analyze(txs, fees, llm=fake_llm)
    assert calls == ["KCP 알수없는상점"]
    assert result["subscriptions"][0]["candidates"][0]["service"] == "Mystery"


def test_alias_for_amount_only(demo_transactions, fees):
    aliases = {("NICE페이", 9900): "Disney+", ("NICE페이", 1): "Other"}
    result = explain_charge("NICE페이", 9900, demo_transactions, fees, aliases=aliases)
    assert result["candidates"][0]["service"] == "Disney+"


# --- 해지 안내 ---


def test_cancel_info_by_payment_channel(demo_transactions, fees):
    subs = {s["service"]: s for s in analyze(demo_transactions, fees)["subscriptions"]}
    assert subs["Speak"]["cancel"]["via"] == "google_play"
    assert subs["iCloud+"]["cancel"]["via"] == "app_store"
    assert subs["Netflix"]["cancel"] == {"via": "web", "url": "https://help.netflix.com/en/node/407",
                                         "host": "help.netflix.com", "verified": True, "steps": None}
    assert subs["Speak"]["cancel"]["host"] == "play.google.com"
    assert subs["Speak"]["cancel"]["steps"]


def test_cancel_info_without_web_url_gives_app_steps(fees):
    from analysis.infer import cancel_info

    info = cancel_info("없는서비스", None, fees)
    assert info["via"] == "app" and info["url"] is None
    assert "없는서비스" in info["steps"]


# --- 구독 상태 · 알림 · 비중 ---


def _monthly(merchant, amount, months, day=5, year=2026):
    return [Transaction(date(year, m, day), merchant, amount) for m in months]


def test_demo_subscriptions_are_active_with_share(demo_transactions, fees):
    result = analyze(demo_transactions, fees)
    assert {s["status"] for s in result["subscriptions"]} == {"active"}
    assert sum(s["share"] for s in result["subscriptions"]) == pytest.approx(100, abs=0.5)
    assert result["as_of"] == max(t.date for t in demo_transactions).isoformat()


def test_missed_payment_is_lapsed_not_cancelled(fees):
    # 1~6월 매달 결제, 7월 결제 없음. 기준일 7/20 이면 예상일 7/5 + 7일이 지났다.
    txs = _monthly("NETFLIX.COM", 13500, range(1, 7)) + [Transaction(date(2026, 7, 20), "GS25", 1000)]
    result = analyze(txs, fees)
    netflix = result["subscriptions"][0]
    assert (netflix["status"], netflix["missed_cycles"]) == ("lapsed", 1)
    assert result["monthly_total"] == 13500  # 한 번 빠진 건 잔액 부족일 수도 있어 합계에 남긴다
    assert any(a["type"] == "lapsed" for a in result["alerts"])


def test_long_stopped_subscription_leaves_total(fees):
    # 1~3월 결제 후 끊김. 첫 명세서에 이미 해지한 구독의 기록이 남아 있는 경우.
    txs = _monthly("NETFLIX.COM", 13500, range(1, 4)) + [Transaction(date(2026, 9, 30), "GS25", 1000)]
    result = analyze(txs, fees)
    assert result["subscriptions"][0]["missed_cycles"] >= 2
    assert result["monthly_total"] == 0


def test_user_cancel_survives_old_charges(fees):
    txs = _monthly("NETFLIX.COM", 13500, range(1, 7))
    states = {"NETFLIX.COM": ("cancelled", date(2026, 6, 20))}
    result = analyze(txs, fees, states=states)
    netflix = result["subscriptions"][0]
    assert netflix["status"] == "cancelled"
    assert netflix["share"] is None
    assert result["monthly_total"] == 0
    assert result["alerts"] == []


def test_charge_after_cancel_is_flagged(fees):
    txs = _monthly("NETFLIX.COM", 13500, range(1, 8))
    states = {"NETFLIX.COM": ("cancelled", date(2026, 6, 20))}
    result = analyze(txs, fees, states=states)
    netflix = result["subscriptions"][0]
    assert netflix["status"] == "active" and netflix["recharged_after_cancel"]
    assert result["alerts"][0]["type"] == "recharged_after_cancel"


def test_price_change_alert(demo_transactions, fees):
    alerts = analyze(demo_transactions, fees)["alerts"]
    netflix = next(a for a in alerts if a["type"] == "price_change")
    assert (netflix["service"], netflix["before"], netflix["after"]) == ("Netflix", 13500, 17000)
    assert alerts.index(netflix) < next(i for i, a in enumerate(alerts) if a["type"] == "needs_review")


def test_no_cancel_until_service_confirmed(demo_transactions, fees):
    nice = next(s for s in analyze(demo_transactions, fees)["subscriptions"] if s["merchant"] == "NICE페이")
    assert nice["confidence"] == "medium"
    assert nice["cancel"] is None


def test_subscriptions_sorted_by_next_payment(demo_transactions, fees):
    dates = [s["next_payment_date"] for s in analyze(demo_transactions, fees)["subscriptions"]]
    assert dates == sorted(dates)


# --- 주기 밖 결제 ---


def test_extra_charge_does_not_break_subscription():
    txs = [Transaction(date(2026, m, 26), "NICE페이", 9900) for m in range(5, 11)]
    txs.append(Transaction(date(2026, 10, 29), "NICE페이", 9900))
    [sub] = detect_subscriptions(txs)
    assert sub.cycle == "monthly"
    assert len(sub.charges) == 6
    assert sub.next_date == date(2026, 11, 26)


def test_frequent_same_price_purchases_are_not_subscription():
    """매일 같은 가격의 커피 중 한 달 간격인 두 잔을 구독으로 오인하지 않는다."""
    txs = [Transaction(date(2026, 5, 1) + timedelta(days=d), "스타벅스", 4500) for d in range(45)]
    assert detect_subscriptions(txs) == []


def test_parser_reads_card_and_transfer_mix():
    data = (
        "거래일자,구분,결제수단,내용,금액,메모\n"
        "2026.04.07,카드결제,KB국민 신용 7730,NETFLIX.COM,\"13,500\",\n"
        "2026.04.21,자동이체,신한 입출금 ***-***-118204,SKT 통신요금,\"49,000\",고정비\n"
    ).encode()
    assert parse_statement("mix.csv", data) == [
        Transaction(date(2026, 4, 7), "NETFLIX.COM", 13500),
        Transaction(date(2026, 4, 21), "SKT 통신요금", 49000),
    ]


def test_parser_image_keeps_spending_only():
    calls = []

    def reader(data, mime_type):
        calls.append(mime_type)
        return [
            {"date": "2026-10-15", "merchant": "GOOGLE*YOUTUBE", "amount": 14900},
            {"date": "2026-10-10", "merchant": "아르바이트 급여", "amount": -820000},  # 입금
            {"date": "언젠가", "merchant": "깨진 줄", "amount": 1000},  # 잘못 읽힌 줄은 건너뜀
        ]

    assert parse_statement("capture.PNG", b"img", reader) == [Transaction(date(2026, 10, 15), "GOOGLE*YOUTUBE", 14900)]
    assert calls == ["image/png"]


@pytest.mark.parametrize(
    "reader, reason",
    [
        (None, "GEMINI_API_KEY"),  # 키 없음
        (lambda data, mime: None, "읽지 못했습니다"),  # Gemini 실패
        (lambda data, mime: [], "찾지 못했습니다"),  # 거래 목록이 아닌 이미지
    ],
)
def test_parser_image_failures(reader, reason):
    with pytest.raises(UnsupportedFormat) as e:
        parse_statement("capture.jpg", b"img", reader)
    assert reason in e.value.reason


def test_gemini_inferer_caches_success_only(monkeypatch):
    from types import SimpleNamespace

    from analysis.llm import GeminiInferer

    monkeypatch.setattr(GeminiInferer, "_cache", {})
    replies = [None, '{"candidates": [{"service": "Melon", "confidence": "medium", "reason": "r"}]}']
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        text = replies[len(calls) - 1]
        return SimpleNamespace(status="completed" if text else "failed", output_text=text)

    inferer = GeminiInferer(client=SimpleNamespace(interactions=SimpleNamespace(create=create)), model="m")
    args = ("멜론 정기결제", 10900, "monthly", ["2026-04-16", "2026-05-16"], [])
    assert inferer(*args) == []  # 실패는 캐시하지 않음
    assert inferer(*args)[0]["service"] == "Melon"
    assert inferer(*args)[0]["service"] == "Melon"
    assert len(calls) == 2
