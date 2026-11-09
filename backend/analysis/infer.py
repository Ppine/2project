"""반복 결제의 실제 출처(서비스) 추론과 결제 설명.

순서: 사용자 확인 매핑 → 가맹점 표기 속 서비스명 → 구독료 금액 일치 → Gemini.
결과는 단정이 아니라 후보 + 신뢰도(high/medium/low) + 근거로 낸다.

금액 일치는 PG사·앱마켓·공유 대행사처럼 표기가 서비스를 가리는 결제에서만 근거로 쓴다. 직접 결제 가맹점은 이름이 곧
서비스라서, 이름과 관계없는 요금이 금액만 같다고 그 서비스로 보지 않는다 (예: 멜론 10,900원 ≠ Wavve).
"""

import csv
import math
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
# 결제경로 열 -> Fee.channel. web·telecom 은 어디서 결제돼도 후보가 되는 일반 요금이다.
ROUTE_CHANNELS = {"app_store": "apple", "google_play": "google", "share": "share"}
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
    # 한글 표기 (normalize_name 을 거친 형태: 공백·기호 없음)
    "넷플릭스": "Netflix",
    "디즈니": "Disney+",
    "티빙": "TVING",
    "웨이브": "Wavve",
    "왓챠": "WATCHA",
    "유튜브프리미엄": "YouTube Premium",
    "유튜브뮤직": "YouTube Music",
    "스포티파이": "Spotify",
    "애플뮤직": "Apple Music",
    "밀리의서재": "Millie Library",
    "배민클럽": "Baemin Club",
    "클래스101": "CLASS101+",
    "듀오링고": "Duolingo",
    "캔바": "Canva",
    "캡컷": "CapCut",
    "퍼플렉시티": "Perplexity",
    "챗GPT": "ChatGPT",
    "챗지피티": "ChatGPT",
    "멜론": "Melon",
    "MELON": "Melon",
    "지니뮤직": "Genie Music",
    "플로": "FLO",
    "벅스": "Bugs",
    "라프텔": "Laftel",
    "LAFTEL": "Laftel",
    "리디셀렉트": "RIDI Select",
    "노션": "Notion",
    "컬리멤버스": "Kurly Members",
    "우주패스": "T Universe Pass",
}
# 서비스가 여럿인 브랜드의 한글 표기 -> 구독료 표 서비스명의 첫 단어. `카카오` 3,900원은 Kakao 계열 요금 중에서만 찾는다.
BRAND_ALIASES = {
    "카카오": "KAKAO",
    "애플": "APPLE",
    "구글": "GOOGLE",
    "어도비": "ADOBE",
    "마이크로소프트": "MICROSOFT",
    "네이버": "NAVER",
    "유튜브": "YOUTUBE",
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
    route: str = ""  # 결제경로 열: web | app_store | google_play | share | telecom (빈 값이면 요금제명으로 추측)
    category: str = ""
    max_members: int | None = None  # 함께 쓸 수 있는 최대 인원. 1/N 송금 추론에 쓴다
    share_platform: str = ""  # 공유 대행사 요금이면 대행사 이름

    @property
    def channel(self) -> str | None:
        """앱마켓 전용 요금이면 "apple"/"google", 공유 대행사 요금이면 "share", 웹·일반 요금이면 None.

        결제경로 열이 있으면 그것을 따른다. 없으면 요금제명으로 추측한다
        (비고에는 "iOS 앱 결제는 별도" 같은 안내가 섞여 있어 요금제명만 본다).
        """
        if self.route:
            return ROUTE_CHANNELS.get(self.route)
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
    """CSV 한 행. 결제경로·분류·최대인원·대행사 열은 없어도 된다 (예전 형식 호환)."""
    price = float(row["가격"])
    members = (row.get("최대인원") or "").strip()
    return Fee(
        service=row["서비스"],
        plan=row["요금제"],
        price=int(price) if price.is_integer() else price,
        currency=row["통화"],
        cycle=FEE_CYCLES.get(row["결제주기"], "monthly"),
        note=row.get("비고") or "",
        cancel_url=row.get("해지 관리 URL") or "",
        route=(row.get("결제경로") or "").strip(),
        category=(row.get("분류") or "").strip(),
        max_members=int(members) if members else None,
        share_platform=(row.get("대행사") or "").strip(),
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

    # PG사·앱마켓은 `GOOGLE*YOUTUBE` 의 YOUTUBE 처럼 * 뒤가 서비스명이고, 직접 결제는 표기 전체가 이름이다
    # (`ADOBE *PHOTOGPHY` 는 ADOBE 쪽이 서비스명).
    name = (merchant.hint or merchant.cleaned) if merchant.intermediary else merchant.cleaned
    service = _service_from_name(name, fees)
    if service:
        evidence = [f"가맹점 표기 '{merchant.cleaned}'에 서비스명 포함", count]
        return _result([_candidate(service, _plan_for(service, sub, fees), "high")], evidence)

    matches = _price_matches(sub.amount, sub.cycle, merchant.channel, fees, merchant.intermediary)
    unrelated = []
    if not merchant.intermediary:
        unrelated = [f for f in matches if not _same_brand(merchant.cleaned, f.service)]
        matches = [f for f in matches if f not in unrelated]
    services = sorted({f.service for f in matches})
    if services:
        confidence = "high" if len(services) == 1 else "medium"
        candidates = [_candidate(s, next(f.plan for f in matches if f.service == s), confidence) for s in services]
        names = ", ".join(f"{f.service} {f.plan}" for f in matches)
        evidence = [f"금액 {sub.amount:,}원이 {names} 요금과 일치", count]
        if merchant.channel == "share":
            evidence.append(f"{merchant.intermediary} 공유 구독 — 원 서비스 요금을 여러 명이 나눠 내는 결제")
        elif merchant.intermediary:
            evidence.append(f"{merchant.intermediary} 결제 — 실제 가맹점 표기가 없음")
        return _result(candidates, evidence)

    # 사람에게 보내는 반복 이체는 구독을 지인과 1/N 로 나눠 내는 것일 수 있다. 금액만으로는 단정할 수 없어 low.
    if merchant.is_transfer:
        splits = _split_matches(sub.amount, sub.cycle, fees)
        if splits:
            candidates = [_candidate(f.service, f.plan, "low") for f, _ in splits]
            evidence = [count] + [
                f"{f.service} {f.plan} {f.price:,}원 ÷ {n}명 ≈ {sub.amount:,}원 — 함께 나눠 내는 구독일 수 있어요"
                for f, n in splits
            ]
            return _result(candidates, evidence)

    if llm:
        dates = [tx.date.isoformat() for tx in sub.charges]
        guessed = llm(merchant.cleaned, sub.amount, sub.cycle, dates, fees)
        if guessed:
            candidates = [_candidate(g["service"], None, g["confidence"]) for g in guessed]
            evidence = [count] + [f"LLM 추론: {g['reason']}" for g in guessed]
            return _result(candidates, evidence)

    if unrelated:
        candidates = [_candidate(f.service, f.plan, "low") for f in unrelated]
        names = ", ".join(f"{f.service} {f.plan}" for f in unrelated)
        evidence = [count, f"금액 {sub.amount:,}원이 {names} 요금과 같지만 가맹점 이름과 맞지 않아 단정하지 않음"]
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
        matches = _price_matches(amount, "monthly", info.channel, fees, info.intermediary)
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
            "cancel": cancel_info(top["service"], sub.merchant.channel, fees, sub.merchant.intermediary)
            if confirmed else None,
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


def cancel_info(service: str, channel: str | None, fees: list[Fee], intermediary: str | None = None) -> dict:
    """해지 경로. 서비스가 확정된 구독에만 준다 (후보만으로 해지 대상을 정하지 않는다).

    URL 은 돈구마가 관리하는 구독료 표나 앱마켓 공식 주소에서만 가져온다. 이동할 도메인(host)을
    함께 내려 사용자가 결제 사이트로 가기 전에 확인할 수 있게 한다.
    웹 해지 주소가 없는 서비스는 앱에서 해지하는 방법(steps)만 준다.
    공유 대행사 결제는 원 서비스가 아니라 대행사에서 파티를 나가야 결제가 멈춘다.
    """
    if channel == "share":
        url = next((f.cancel_url for f in fees if f.share_platform == intermediary and f.cancel_url), None)
        steps = f"{intermediary} 앱 > 내 파티 > 파티 나가기 (원 서비스에서 해지하는 것이 아님)"
        if url:
            return _cancel("share", url, steps)
        return {"via": "share", "url": None, "host": None, "verified": False, "steps": steps}
    if channel in MARKET_CANCEL:
        via, url = MARKET_CANCEL[channel]
        return _cancel(via, url, MARKET_STEPS[via])
    # 앱마켓·공유 대행사 요금의 URL 은 그 경로로 결제했을 때만 맞다. 웹 해지 주소는 일반 요금에서만 찾는다.
    url = next((f.cancel_url for f in fees if f.service == service and f.channel is None and f.cancel_url), None)
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


def _same_brand(merchant: str, service: str) -> bool:
    """가맹점 이름에 서비스 브랜드(서비스명 첫 단어)가 들어 있는가. `카카오` ↔ `Kakao Emoticon Plus`."""
    key = normalize_name(merchant)
    brand = normalize_name(service.split()[0])
    return brand in key or any(alias in key for alias, b in BRAND_ALIASES.items() if b == brand)


def _channel_ok(fee: Fee, channel: str | None, intermediary: str | None = None) -> bool:
    """앱마켓 전용 요금은 그 앱마켓 결제에서만, 웹 요금은 어디서든 후보가 된다.

    공유 대행사 결제는 1인분 금액이라 원가(웹 요금)와 비교하지 않고, 같은 대행사의 공유 요금만 본다.
    """
    if channel == "share":
        return fee.channel == "share" and (intermediary is None or fee.share_platform == intermediary)
    return fee.channel is None or fee.channel == channel


def _price_matches(amount: int, cycle: str, channel: str | None, fees: list[Fee],
                   intermediary: str | None = None) -> list[Fee]:
    return [f for f in fees if f.currency == "KRW" and f.price == amount and f.cycle == cycle
            and _channel_ok(f, channel, intermediary)]


def _split_matches(amount: int, cycle: str, fees: list[Fee]) -> list[tuple[Fee, int]]:
    """금액이 어떤 요금을 n명이 나눈 몫인가. 1원·10원·100원 단위 올림·내림까지 같은 몫으로 본다.

    최대인원이 2명 이상인 웹 요금만 본다 (공유가 불가능한 개인 요금, 앱마켓 요금은 나눠 내지 않는다).
    """
    found = []
    for fee in fees:
        if fee.currency != "KRW" or fee.cycle != cycle or fee.channel is not None or (fee.max_members or 1) < 2:
            continue
        for n in range(2, fee.max_members + 1):
            share = fee.price / n
            if amount in {math.floor(share / unit) * unit for unit in (1, 10, 100)} | {
                math.ceil(share / unit) * unit for unit in (1, 10, 100)
            }:
                found.append((fee, n))
    return found


def _plan_for(service: str, sub: Recurring, fees: list[Fee]) -> str | None:
    """서비스 안에서 금액이 같은 요금제. 같은 금액이 여러 경로에 있으면 결제 경로가 맞는 요금을 먼저 고른다."""
    same = [f for f in fees if f.service == service and f.price == sub.amount]
    merchant = sub.merchant
    fitting = [f for f in same if _channel_ok(f, merchant.channel, merchant.intermediary)]
    exact = [f for f in fitting if f.channel == merchant.channel]
    return next((f.plan for f in exact + fitting + same), None)


def _candidate(service: str, plan: str | None, confidence: str) -> dict:
    return {"service": service, "plan": plan, "confidence": confidence}


def _result(candidates: list[dict], evidence: list[str]) -> dict:
    confidence = candidates[0]["confidence"] if candidates else "low"
    return {"confidence": confidence, "candidates": candidates, "evidence": evidence}
