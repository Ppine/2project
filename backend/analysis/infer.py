"""반복 결제의 실제 출처(서비스) 추론과 결제 설명.

순서: 사용자 확인 매핑 → 가맹점 표기 속 서비스명 → 구독료 금액 일치 → Claude.
결과는 단정이 아니라 후보 + 신뢰도(high/medium/low) + 근거로 낸다.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from .clean import describe_merchant, normalize_name
from .detect import Recurring, cycle_of, detect_subscriptions
from .parsers import Transaction

CYCLE_LABELS = {"monthly": "매월", "yearly": "매년"}
FEE_CYCLES = {"월": "monthly", "년": "yearly"}

# 구독료 표에 없는 가맹점 표기 -> 서비스명
KNOWN_MERCHANTS = {
    "와우멤버십": "Coupang Wow",
    "네이버플러스": "Naver Plus Membership",
    "NETFLIX": "Netflix",
    "YOUTUBEPREMIUM": "YouTube Premium",
    "YOUTUBEMUSIC": "YouTube Music",
    "OPENAI": "ChatGPT",
    "ANTHROPIC": "Claude",
}


@dataclass(frozen=True)
class Fee:
    service: str
    plan: str
    price: int | float
    currency: str
    cycle: str
    note: str = ""
    cancel_url: str = ""

    @property
    def channel(self) -> str | None:
        """앱마켓 전용 요금이면 "apple"/"google", 웹·일반 요금이면 None.

        비고에는 "iOS 앱 결제는 별도" 같은 안내가 섞여 있어 요금제명만 본다.
        """
        text = self.plan
        if "App Store" in text or "iOS 앱" in text:
            return "apple"
        if "Google Play" in text or "Galaxy Store" in text or "Android 앱" in text:
            return "google"
        return None


def load_fees(path: str | Path) -> list[Fee]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [fee_from_row(row) for row in csv.DictReader(f)]


def fee_from_row(row: dict) -> Fee:
    price = float(row["가격"])
    return Fee(
        service=row["서비스"],
        plan=row["요금제"],
        price=int(price) if price.is_integer() else price,
        currency=row["통화"],
        cycle=FEE_CYCLES.get(row["결제주기"], "monthly"),
        note=row.get("비고", ""),
        cancel_url=row.get("해지 관리 URL", ""),
    )


def identify(sub: Recurring, fees: list[Fee], aliases: dict[str, str] | None = None, llm=None) -> dict:
    """반복 결제 한 건의 출처 후보."""
    merchant = sub.merchant
    count = f"{CYCLE_LABELS[sub.cycle]} {len(sub.charges)}회 결제"

    service = (aliases or {}).get(merchant.cleaned)
    if service:
        return _result([_candidate(service, _plan_for(service, sub, fees), "high")], ["사용자가 확인한 매핑", count])

    service = _service_from_name(merchant.hint or merchant.cleaned, fees)
    if service:
        evidence = [f"가맹점 표기 '{merchant.cleaned}'에 서비스명 포함", count]
        return _result([_candidate(service, _plan_for(service, sub, fees), "high")], evidence)

    matches = _price_matches(sub.amount, sub.cycle, merchant.channel, fees)
    services = sorted({f.service for f in matches})
    if services:
        confidence = "high" if len(services) == 1 else "medium"
        candidates = [_candidate(s, next(f.plan for f in matches if f.service == s), confidence) for s in services]
        names = ", ".join(f"{f.service} {f.plan}" for f in matches)
        evidence = [f"금액 {sub.amount:,}원이 {names} 요금과 일치", count]
        if merchant.intermediary:
            evidence.append(f"{merchant.intermediary} 결제 — 실제 가맹점 표기가 없음")
        return _result(candidates, evidence)

    if llm:
        dates = [tx.date.isoformat() for tx in sub.charges]
        guessed = llm(merchant.cleaned, sub.amount, sub.cycle, dates, fees)
        if guessed:
            candidates = [_candidate(g["service"], None, g["confidence"]) for g in guessed]
            evidence = [count] + [f"LLM 추론: {g['reason']}" for g in guessed]
            return _result(candidates, evidence)

    return _result([], [count, "알려진 구독료·가맹점 표기와 일치하는 서비스가 없음"])


def explain_charge(
    merchant: str, amount: int, transactions: list[Transaction], fees: list[Fee], aliases=None, llm=None
) -> dict:
    """가맹점·금액으로 결제를 찾아 정체를 설명한다 (MCP explain_charge)."""
    target = describe_merchant(merchant).cleaned
    matched = sorted(
        (tx for tx in transactions if tx.amount == amount and _same_merchant(target, tx.merchant)),
        key=lambda tx: tx.date,
    )
    base = {"merchant": merchant, "amount": amount, "dates": [tx.date.isoformat() for tx in matched]}
    if not matched:
        return {**base, "found": False, "is_subscription": False, "confidence": "low", "candidates": [],
                "evidence": ["명세서에서 해당 가맹점·금액의 결제를 찾지 못함"]}

    cycle = cycle_of(matched)
    if not cycle:
        info = describe_merchant(matched[0].merchant)
        matches = _price_matches(amount, "monthly", info.channel, fees)
        evidence = [f"{len(matched)}회 결제 — 반복 결제가 아니어서 구독이 아닌 일반 결제로 보임"]
        if matches:
            evidence.append("금액이 일치하는 구독 요금이 있으나 반복되지 않아 단정할 수 없음")
        candidates = [_candidate(f.service, f.plan, "low") for f in matches]
        return {**base, "found": True, "is_subscription": False, "confidence": "low",
                "candidates": candidates, "evidence": evidence}

    sub = Recurring(describe_merchant(matched[-1].merchant), matched[-1].merchant, cycle, matched)
    result = identify(sub, fees, aliases, llm)
    return {**base, "found": True, "is_subscription": True, "cycle": cycle,
            "next_payment_date": sub.next_date.isoformat(), **result}


def analyze(transactions: list[Transaction], fees: list[Fee], aliases=None, llm=None) -> dict:
    """구독 목록과 월 합계 (MCP list_subscriptions, 웹 대시보드)."""
    subscriptions = []
    for sub in detect_subscriptions(transactions):
        result = identify(sub, fees, aliases, llm)
        top = result["candidates"][0] if result["candidates"] else None
        subscriptions.append({
            "service": top["service"] if top and result["confidence"] == "high" else sub.raw_merchant,
            "plan": top["plan"] if top and result["confidence"] == "high" else None,
            "merchant": sub.raw_merchant,
            "amount": sub.amount,
            "cycle": sub.cycle,
            "monthly_amount": sub.monthly_amount,
            "next_payment_date": sub.next_date.isoformat(),
            "first_charge_date": sub.charges[0].date.isoformat(),
            "charge_count": len(sub.charges),
            "price_history": sub.price_history,
            **result,
        })
    return {
        "subscriptions": subscriptions,
        "monthly_total": sum(s["monthly_amount"] for s in subscriptions),
        "currency": "KRW",
    }


def _same_merchant(target: str, raw: str) -> bool:
    cleaned = describe_merchant(raw).cleaned
    return cleaned == target or normalize_name(cleaned).startswith(normalize_name(target))


def _service_from_name(text: str, fees: list[Fee]) -> str | None:
    key = normalize_name(text)
    for alias, service in KNOWN_MERCHANTS.items():
        if alias in key:
            return service
    # 긴 이름부터 비교해 "YouTube Music" 이 "YouTube" 보다 먼저 맞도록 한다.
    for service in sorted({f.service for f in fees}, key=len, reverse=True):
        if normalize_name(service) in key:
            return service
    return None


def _price_matches(amount: int, cycle: str, channel: str | None, fees: list[Fee]) -> list[Fee]:
    def channel_ok(fee: Fee) -> bool:
        # 앱마켓 전용 요금은 해당 앱마켓 결제에서만, 웹 요금은 어디서든 후보가 된다.
        return fee.channel is None or fee.channel == channel

    return [f for f in fees if f.currency == "KRW" and f.price == amount and f.cycle == cycle and channel_ok(f)]


def _plan_for(service: str, sub: Recurring, fees: list[Fee]) -> str | None:
    return next((f.plan for f in fees if f.service == service and f.price == sub.amount), None)


def _candidate(service: str, plan: str | None, confidence: str) -> dict:
    return {"service": service, "plan": plan, "confidence": confidence}


def _result(candidates: list[dict], evidence: list[str]) -> dict:
    confidence = candidates[0]["confidence"] if candidates else "low"
    return {"confidence": confidence, "candidates": candidates, "evidence": evidence}
