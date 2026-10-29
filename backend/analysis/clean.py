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


@dataclass(frozen=True)
class MerchantInfo:
    cleaned: str
    intermediary: str | None  # PG사·앱마켓 이름. 직접 결제면 None
    channel: str | None  # "apple" | "google" | "pg" | None
    hint: str | None  # `GOOGLE*YOUTUBE` 의 YOUTUBE 처럼 중개사 뒤에 붙은 실제 서비스 표기


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
    return MerchantInfo(cleaned, None, None, hint)


def normalize_name(name: str) -> str:
    """서비스명 비교용: 대문자, 영숫자·한글만."""
    return re.sub(r"[^0-9A-Z가-힣]", "", name.upper())
