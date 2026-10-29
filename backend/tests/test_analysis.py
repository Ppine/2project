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
    assert subs["Netflix"]["cancel"] == {"via": "web", "url": "https://help.netflix.com/en/node/407"}


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
