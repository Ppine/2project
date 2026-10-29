"""반복 결제 탐지.

1. (정제된 가맹점, 금액) 이 같은 거래를 묶고, 간격이 월(28~31일)·연(335~370일)로 일정하면 반복 구간으로 본다.
   주기 사이에 끼어든 같은 금액의 일회성 결제는 반복 구간에서 빼되, 반복 결제보다 훨씬 적을 때만 허용한다.
2. 직접 결제 가맹점은 같은 가맹점의 반복 구간이 이어지면 하나의 구독으로 합친다 (요금 인상·요금제 변경).
   PG사·앱마켓은 한 가맹점 표기 아래 여러 서비스가 섞이므로 합치지 않는다.

금액은 정확히 같아야 같은 묶음으로 본다. 원화 구독료는 매달 같은 금액이 찍히고,
일반 소비의 우연한 금액 근접을 구독으로 오인하지 않기 위해서다.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .clean import MerchantInfo, describe_merchant
from .parsers import Transaction

CYCLES = {
    "monthly": (28, 31),
    "yearly": (335, 370),
}
MIN_CHARGES = 2
MAX_EXTRA_RATIO = 3  # 반복 결제 3건당 끼어든 결제 1건까지


@dataclass
class Recurring:
    merchant: MerchantInfo
    raw_merchant: str
    cycle: str
    charges: list[Transaction] = field(default_factory=list)

    @property
    def amount(self) -> int:
        return self.charges[-1].amount

    @property
    def last_date(self) -> date:
        return self.charges[-1].date

    @property
    def next_date(self) -> date:
        return add_months(self.last_date, 1 if self.cycle == "monthly" else 12)

    @property
    def monthly_amount(self) -> int:
        return self.amount if self.cycle == "monthly" else round(self.amount / 12)

    @property
    def price_history(self) -> list[dict]:
        history = []
        for tx in self.charges:
            if not history or history[-1]["amount"] != tx.amount:
                history.append({"since": tx.date.isoformat(), "amount": tx.amount})
        return history


def detect_subscriptions(transactions: list[Transaction]) -> list[Recurring]:
    groups = defaultdict(list)
    for tx in transactions:
        groups[(describe_merchant(tx.merchant).cleaned, tx.amount)].append(tx)

    segments = []
    for txs in groups.values():
        txs.sort(key=lambda t: t.date)
        found = find_cycle(txs)
        if found:
            cycle, charges = found
            segments.append(Recurring(describe_merchant(charges[0].merchant), charges[-1].merchant, cycle, charges))

    return sorted(_merge_price_changes(segments), key=lambda r: r.charges[0].date)


def find_cycle(txs: list[Transaction]) -> tuple[str, list[Transaction]] | None:
    """정렬된 거래에서 일정한 주기로 이어지는 가장 긴 결제 사슬과 그 주기.

    예: 매월 26일 결제 사이의 29일 결제 한 건은 사슬에서 빠진다. 끼어든 결제가 많으면(매일 사는 커피처럼)
    우연히 한 달 간격인 두 건을 구독으로 오인하지 않도록 None.
    """
    for cycle, (low, high) in CYCLES.items():
        best: list[Transaction] = []
        for start in range(len(txs)):
            chain = [txs[start]]
            for tx in txs[start + 1:]:
                gap = (tx.date - chain[-1].date).days
                if low <= gap <= high:
                    chain.append(tx)
                elif gap > high:
                    break
            if len(chain) > len(best):
                best = chain
        extras = len(txs) - len(best)
        if len(best) >= MIN_CHARGES and extras * MAX_EXTRA_RATIO <= len(best):
            return cycle, best
    return None


def cycle_of(txs: list[Transaction]) -> str | None:
    """정렬된 거래들이 일정한 주기로 반복되면 그 주기를, 아니면 None."""
    if len(txs) < MIN_CHARGES:
        return None
    gaps = [(b.date - a.date).days for a, b in zip(txs, txs[1:])]
    for cycle, (low, high) in CYCLES.items():
        if all(low <= g <= high for g in gaps):
            return cycle
    return None


def _merge_price_changes(segments: list[Recurring]) -> list[Recurring]:
    by_merchant = defaultdict(list)
    merged = []
    for seg in segments:
        if seg.merchant.intermediary:
            merged.append(seg)
        else:
            by_merchant[seg.merchant.cleaned].append(seg)

    for segs in by_merchant.values():
        segs.sort(key=lambda s: s.charges[0].date)
        current = segs[0]
        for seg in segs[1:]:
            joined = current.charges + seg.charges
            if seg.cycle == current.cycle and cycle_of(joined) == current.cycle:
                current = Recurring(current.merchant, seg.raw_merchant, current.cycle, joined)
            else:
                merged.append(current)
                current = seg
        merged.append(current)
    return merged


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))
