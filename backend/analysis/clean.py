"""가맹점명 정제와 결제대행사(PG사)·앱마켓 판별."""

import re
from dataclasses import dataclass

# 정제된 가맹점명 접두어 -> 표시명
PG_ALIASES = {
    "토스페이먼츠": "토스페이먼츠",
    "KG이니시스": "KG이니시스",
    "이니시스": "KG이니시스",
    "NICE페이": "NICE페이",
    "나이스페이": "NICE페이",
    "KCP": "NHN KCP",
    "다날": "다날",
    "PAYPAL": "PayPal",
}
APP_MARKETS = {
    "APPLE.COM/BILL": "apple",
    "GOOGLE": "google",
}
# 구독 공유 대행사. 여러 명이 한 계정을 나눠 쓰고, 카드에는 대행사 이름으로 1인분(원가 ÷ N + 수수료)이 찍힌다.
SHARE_PLATFORMS = {
    "피클플러스": "피클플러스",
    "PICKLEPLUS": "피클플러스",
    "PICKLE PLUS": "피클플러스",
    "링키드": "링키드",
    "LINKID": "링키드",
    "벗츠": "벗츠",
}
# 사람에게 보낸 이체. 구독을 지인과 1/N 로 나눠 낼 때 이렇게 찍힌다.
TRANSFER_PREFIXES = ("이체 ", "송금 ", "토스 송금", "카카오페이 송금")


@dataclass(frozen=True)
class MerchantInfo:
    cleaned: str
    intermediary: str | None  # PG사·앱마켓 이름. 직접 결제면 None
    channel: str | None  # "apple" | "google" | "pg" | "share" | None
    hint: str | None  # `GOOGLE*YOUTUBE` 의 YOUTUBE 처럼 중개사 뒤에 붙은 실제 서비스 표기

    @property
    def is_transfer(self) -> bool:
        """사람에게 보낸 이체인가 (`이체 박OO`)."""
        return self.intermediary is None and self.cleaned.startswith(TRANSFER_PREFIXES)


def clean_merchant(raw: str) -> str:
    name = raw.upper()
    name = re.sub(r"\(주\)|㈜|주식회사", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def describe_merchant(raw: str) -> MerchantInfo:
    cleaned = clean_merchant(raw)
    hint = None
    if "*" in cleaned:
        head, _, tail = cleaned.partition("*")
        hint = tail.strip() or None
        head = head.strip()
    else:
        head = cleaned

    for prefix, market in APP_MARKETS.items():
        if head.startswith(prefix):
            return MerchantInfo(cleaned, prefix, market, hint)
    for prefix, name in PG_ALIASES.items():
        if head.startswith(prefix.upper()):
            return MerchantInfo(cleaned, name, "pg", hint)
    for prefix, name in SHARE_PLATFORMS.items():
        if head.startswith(prefix):
            return MerchantInfo(cleaned, name, "share", hint)
    return MerchantInfo(cleaned, None, None, hint)


def normalize_name(name: str) -> str:
    """서비스명 비교용: 대문자, 영숫자·한글만."""
    return re.sub(r"[^0-9A-Z가-힣]", "", name.upper())
