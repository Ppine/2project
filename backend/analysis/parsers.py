"""카드사 명세서 파일을 공통 스키마(Transaction)로 바꾼다.

카드사 포맷은 FORMATS 에 헤더 매핑으로 등록한다. 매핑에 없는 컬럼(이용카드 등)은
읽지 않으므로 카드번호는 저장 단계까지 넘어가지 않는다.
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime

UNSUPPORTED_MESSAGE = "지원하지 않는 명세서 형식입니다"

# 공통 필드 -> 명세서 헤더
FORMATS = {
    "demo_card": {
        "date": "이용일자",
        "merchant": "가맹점명",
        "amount": "이용금액",
        "approval_no": "승인번호",
    },
}
REQUIRED_FIELDS = ("date", "merchant", "amount")


class UnsupportedFormat(Exception):
    def __init__(self, reason=""):
        super().__init__(UNSUPPORTED_MESSAGE)
        self.reason = reason


@dataclass(frozen=True)
class Transaction:
    date: date
    merchant: str
    amount: int
    approval_no: str = ""


def parse_statement(filename: str, data: bytes) -> list[Transaction]:
    if not filename.lower().endswith(".csv"):
        raise UnsupportedFormat("csv 파일만 지원합니다")

    text = _decode(data)
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    mapping = _detect_format(headers)

    transactions = []
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if not any(row.values()):
            continue
        try:
            transactions.append(
                Transaction(
                    date=_parse_date(row[mapping["date"]]),
                    merchant=row[mapping["merchant"]],
                    amount=_parse_amount(row[mapping["amount"]]),
                    approval_no=row.get(mapping.get("approval_no", ""), ""),
                )
            )
        except ValueError as e:
            raise UnsupportedFormat(f"{reader.line_num}행을 읽을 수 없습니다: {e}") from e

    if not transactions:
        raise UnsupportedFormat("거래 내역이 없습니다")
    return transactions


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnsupportedFormat("인코딩을 읽을 수 없습니다")


def _detect_format(headers: list[str]) -> dict:
    for mapping in FORMATS.values():
        if all(mapping[field] in headers for field in REQUIRED_FIELDS):
            return mapping
    raise UnsupportedFormat("필수 컬럼(이용일자, 가맹점명, 이용금액)이 없습니다")


def _parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"날짜 형식 오류: {value!r}")


def _parse_amount(value: str) -> int:
    cleaned = re.sub(r"[,\s원]", "", value)
    if not re.fullmatch(r"-?\d+", cleaned):
        raise ValueError(f"금액 형식 오류: {value!r}")
    return int(cleaned)
