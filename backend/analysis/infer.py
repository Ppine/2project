"""반복 결제의 실제 출처(서비스) 추론과 결제 설명.

순서: 사용자 확인 매핑 → 가맹점 표기 속 서비스명 → 구독료 금액 일치 → Gemini.
결과는 단정이 아니라 후보 + 신뢰도(high/medium/low) + 근거로 낸다.
"""

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .clean import describe_merchant, normalize_name
from .detect import Recurring, add_months, detect_subscriptions, find_cycle
from .parsers import Transaction

CYCLE_LABELS = {"monthly": "매월", "yearly": "매년"}
# 앱마켓 결제는 서비스 웹이 아니라 앱마켓 구독 관리 화면에서 해지한다.
MARKET_CANCEL = {
    "google": ("google_play", "https://play.google.com/store/account/subscriptions"),
    "apple": ("app_store", "https://apps.apple.com/account/subscriptions"),
}
MARKET_STEPS = {
    "google_play": "Play 스토어 앱 > 프로필 > 결제 및 정기 결제 > 정기 결제에서 해지",
    "app_store": "iPhone 설정 > 내 이름 > 구독에서 해지",
}
# 예상 결제일이 이만큼 지나도록 결제가 없으면 '결제 확인 안 됨'. 카드사 매입 지연을 감안한 여유다.
GRACE_DAYS = {"monthly": 7, "yearly": 30}
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


def identify(sub: Recurring, fees: list[Fee], aliases: dict | None = None, llm=None) -> dict:
    """반복 결제 한 건의 출처 후보.

    aliases 키는 가맹점 전체(`"NICE페이"`) 또는 가맹점+금액(`("NICE페이", 9900)`).
    PG사는 한 표기 아래 여러 서비스가 섞이므로 금액까지 맞는 매핑을 먼저 쓴다.
    """
    merchant = sub.merchant
    count = f"{CYCLE_LABELS[sub.cycle]} {len(sub.charges)}회 결제"

    aliases = aliases or {}
    service = aliases.get((merchant.cleaned, sub.amount)) or aliases.get(merchant.cleaned)
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

    found = find_cycle(matched)
    if not found:
        info = describe_merchant(matched[0].merchant)
        matches = _price_matches(amount, "monthly", info.channel, fees)
        evidence = [f"{len(matched)}회 결제 — 반복 결제가 아니어서 구독이 아닌 일반 결제로 보임"]
        if matches:
            evidence.append("금액이 일치하는 구독 요금이 있으나 반복되지 않아 단정할 수 없음")
        candidates = [_candidate(f.service, f.plan, "low") for f in matches]
        return {**base, "found": True, "is_subscription": False, "confidence": "low",
                "candidates": candidates, "evidence": evidence}

    cycle, charges = found
    sub = Recurring(describe_merchant(charges[-1].merchant), charges[-1].merchant, cycle, charges)
    result = identify(sub, fees, aliases, llm)
    return {**base, "found": True, "is_subscription": True, "cycle": cycle,
            "next_payment_date": sub.next_date.isoformat(), **result}


def analyze(transactions: list[Transaction], fees: list[Fee], aliases=None, llm=None,
            states: dict | None = None, as_of: date | None = None) -> dict:
    """구독 목록·월 합계·알림 (MCP list_subscriptions, 웹 대시보드).

    states: 사용자가 표시한 구독 상태 (키 -> (status, 표시한 날짜)). 키는 가맹점 또는 (가맹점, 금액).
    as_of: 결제가 끊겼는지 판단하는 기준일 (명세서가 덮는 마지막 날짜). 없으면 마지막 거래일.
    """
    if as_of is None and transactions:
        as_of = max(tx.date for tx in transactions)
    subscriptions = []
    for sub in detect_subscriptions(transactions):
        result = identify(sub, fees, aliases, llm)
        top = result["candidates"][0] if result["candidates"] else None
        confirmed = top is not None and result["confidence"] == "high"
        service = top["service"] if confirmed else sub.raw_merchant
        subscriptions.append({
            "service": service,
            "plan": top["plan"] if confirmed else None,
            "merchant": sub.raw_merchant,
            "amount": sub.amount,
            "cycle": sub.cycle,
            "monthly_amount": sub.monthly_amount,
            "next_payment_date": sub.next_date.isoformat(),
            "first_charge_date": sub.charges[0].date.isoformat(),
            "last_charge_date": sub.last_date.isoformat(),
            "charge_count": len(sub.charges),
            "price_history": sub.price_history,
            "cancel": cancel_info(top["service"], sub.merchant.channel, fees) if confirmed else None,
            **subscription_status(sub, states or {}, as_of),
            **result,
        })
    subscriptions.sort(key=lambda s: s["next_payment_date"])

    counted = [s for s in subscriptions if counts_toward_total(s)]
    total = sum(s["monthly_amount"] for s in counted)
    for s in subscriptions:
        # 소비 분석 비중: 월 환산 구독료 합계 대비. 합계에서 빠진 구독(해지 등)은 None.
        s["share"] = round(s["monthly_amount"] / total * 100, 1) if total and counts_toward_total(s) else None
    return {
        "subscriptions": subscriptions,
        "monthly_total": total,
        "currency": "KRW",
        "as_of": as_of.isoformat() if as_of else None,
        "alerts": build_alerts(subscriptions),
    }


def subscription_status(sub: Recurring, states: dict, as_of: date | None) -> dict:
    """결제 이력과 사용자 표시를 합쳐 지금 상태를 정한다.

    - cancelled: 사용자가 해지했다고 표시했고 그 뒤로 결제가 없음. 예전 결제 기록 때문에 되살아나지 않는다.
    - active + recharged_after_cancel: 해지 표시 뒤에 결제가 또 들어옴. 해지가 안 됐을 수 있다.
    - lapsed: 예상 결제일이 지나도록 결제가 없음. 잔액 부족일 수도 있어 해지로 단정하지 않는다.
    - active: 그 밖.
    """
    key = sub.merchant.cleaned
    state = states.get((key, sub.amount)) or states.get(key)
    if state and state[0] == "cancelled":
        marked_on = state[1]
        if sub.last_date <= marked_on:
            return {"status": "cancelled", "status_changed_on": marked_on.isoformat(), "missed_cycles": 0}
        return {"status": "active", "status_changed_on": marked_on.isoformat(), "missed_cycles": 0,
                "recharged_after_cancel": True}

    missed = 0
    if as_of:
        due = sub.next_date
        grace = timedelta(days=GRACE_DAYS[sub.cycle])
        while due + grace < as_of:
            missed += 1
            due = add_months(due, 1 if sub.cycle == "monthly" else 12)
    return {"status": "lapsed" if missed else "active", "status_changed_on": None, "missed_cycles": missed}


def counts_toward_total(sub: dict) -> bool:
    """월 합계에 넣을 구독. 해지했거나 두 번 이상 결제가 빠진 구독은 이미 끝났을 가능성이 커서 뺀다."""
    return sub["status"] == "active" or (sub["status"] == "lapsed" and sub["missed_cycles"] < 2)


def build_alerts(subscriptions: list[dict]) -> list[dict]:
    """구독 목록과 분리해서 보여 줄 알림. 중요한 것부터."""
    alerts = []
    for s in subscriptions:
        base = {"service": s["service"], "merchant": s["merchant"], "amount": s["amount"]}
        if s.get("recharged_after_cancel"):
            alerts.append({**base, "type": "recharged_after_cancel", "date": s["last_charge_date"],
                           "message": f"해지했다고 표시한 {s['service']}에서 {s['last_charge_date']}에 다시 결제됐어요"})
        if s["status"] == "cancelled":
            continue
        history = s["price_history"]
        if len(history) > 1:
            before, after = history[-2]["amount"], history[-1]["amount"]
            change = after - before
            verb = "올랐어요" if change > 0 else "내렸어요"
            alerts.append({**base, "type": "price_change", "date": history[-1]["since"], "before": before,
                           "after": after, "message": f"{s['service']} 요금이 {abs(change):,}원 {verb} "
                                                     f"({before:,}원 → {after:,}원)"})
        if s["status"] == "lapsed":
            alerts.append({**base, "type": "lapsed", "date": s["next_payment_date"],
                           "missed_cycles": s["missed_cycles"],
                           "message": f"{s['service']} 예상 결제일({s['next_payment_date']})이 지났는데 결제가 없어요. "
                                      "해지했다면 '해지했어요'로 표시해 주세요"})
        if s["confidence"] != "high":
            alerts.append({**base, "type": "needs_review", "date": s["last_charge_date"],
                           "message": f"{s['merchant']} {s['amount']:,}원 결제의 실제 서비스를 확인해 주세요"})
    order = ["recharged_after_cancel", "price_change", "lapsed", "needs_review"]
    return sorted(alerts, key=lambda a: order.index(a["type"]))


def cancel_info(service: str, channel: str | None, fees: list[Fee]) -> dict:
    """해지 경로. 서비스가 확정된 구독에만 준다 (후보만으로 해지 대상을 정하지 않는다).

    URL 은 돈구마가 관리하는 구독료 표나 앱마켓 공식 주소에서만 가져온다. 이동할 도메인(host)을
    함께 내려 사용자가 결제 사이트로 가기 전에 확인할 수 있게 한다.
    웹 해지 주소가 없는 서비스는 앱에서 해지하는 방법(steps)만 준다.
    """
    if channel in MARKET_CANCEL:
        via, url = MARKET_CANCEL[channel]
        return _cancel(via, url, MARKET_STEPS[via])
    url = next((f.cancel_url for f in fees if f.service == service and f.cancel_url), None)
    if url:
        return _cancel("web", url, None)
    return {"via": "app", "url": None, "host": None, "verified": False,
            "steps": f"{service} 앱 > 설정 > 구독·멤버십 관리에서 해지"}


def _cancel(via: str, url: str, steps: str | None) -> dict:
    parsed = urlparse(url)
    return {"via": via, "url": url, "host": parsed.hostname, "verified": parsed.scheme == "https", "steps": steps}


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
