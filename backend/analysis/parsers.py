"""명세서 파일을 공통 스키마(Transaction)로 바꾼다.

CSV 포맷은 FORMATS 에 헤더 매핑으로 등록한다. 매핑에 없는 컬럼(이용카드·결제수단 등)은
읽지 않으므로 카드번호·계좌번호는 저장 단계까지 넘어가지 않는다.
이미지(은행·카드앱 캡처)는 image_reader(Gemini)가 읽은 날짜·내용·금액만 받는다.
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
    # 카드 결제와 계좌이체가 한 파일에 섞인 지출 내역 (가계부 앱 내보내기 형태)
    "card_and_transfer": {
        "date": "거래일자",
        "merchant": "내용",
        "amount": "금액",
    },
}
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".heic": "image/heic",
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


def parse_statement(filename: str, data: bytes, image_reader=None) -> list[Transaction]:
    """image_reader(data, mime_type) -> [{"date", "merchant", "amount"}]: 캡처 이미지에서 지출만 뽑는다."""
    suffix = "." + filename.lower().rpartition(".")[2]
    if suffix in IMAGE_TYPES:
        return _parse_image(data, IMAGE_TYPES[suffix], image_reader)
    if suffix != ".csv":
        raise UnsupportedFormat("csv 또는 이미지(png·jpg) 파일만 지원합니다")

    text = _decode(data)
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    mapping = _detect_format(headers)

    transactions = []
    for row in reader:
        if None in row:  # 헤더보다 칸이 많은 행 (따옴표 없이 쉼표가 들어간 금액 등)
            raise UnsupportedFormat(f"{reader.line_num}번째 줄의 칸 수가 머리글과 다릅니다")
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


def _parse_image(data: bytes, mime_type: str, image_reader) -> list[Transaction]:
    if image_reader is None:
        raise UnsupportedFormat("이미지 명세서를 읽으려면 서버에 GEMINI_API_KEY 가 필요합니다")
    rows = image_reader(data, mime_type)
    if rows is None:
        raise UnsupportedFormat("이미지를 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요")
    transactions = []
    for row in rows:
        try:
            amount = _parse_amount(str(row["amount"]))
            if amount <= 0:  # 입금·환불은 지출 분석 대상이 아니다
                continue
            transactions.append(Transaction(date=_parse_date(str(row["date"])), merchant=str(row["merchant"]).strip(),
                                            amount=amount))
        except (KeyError, ValueError):
            continue  # 잘못 읽힌 한 줄 때문에 전체를 버리지 않는다
    if not transactions:
        raise UnsupportedFormat("이미지에서 결제 내역을 찾지 못했습니다")
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
    raise UnsupportedFormat("필수 컬럼(이용일자·가맹점명·이용금액 또는 거래일자·내용·금액)이 없습니다")


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
