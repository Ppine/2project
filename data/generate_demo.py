"""데모 카드 명세서와 정답 라벨을 만든다.

    python data/generate_demo.py

출력:
    data/demo_card_2026.csv  카드사 명세서 포맷 (이용일자, 이용카드, 가맹점명, 이용금액, 승인번호)
    data/demo_labels.csv     승인번호별 실제 서비스명과 구독 여부
"""

import csv
import random
from datetime import date
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
SEED = 2026
CARD = "본인 9410-12**-****-3381"
MONTHS = [5, 6, 7, 8, 9, 10]
LAST_DAY = date(2026, 10, 28)

# (가맹점 표기, 실제 서비스, 결제일, [(시작월, 금액), ...], 첫 결제월)
# 금액은 docs/service fee modified.csv 의 실제 요금이다.
SUBSCRIPTIONS = [
    ("토스페이먼츠", "YouTube Premium", 15, [(5, 14900)], 5),
    ("NETFLIX.COM", "Netflix", 3, [(5, 13500), (8, 17000)], 5),  # 8월 요금제 인상
    ("PAYPAL *SPOTIFY", "Spotify", 22, [(5, 11990)], 5),
    ("APPLE.COM/BILL", "iCloud+", 8, [(5, 4400)], 5),
    ("쿠팡(와우멤버십)", "Coupang Wow", 11, [(5, 7890)], 5),
    ("NICE페이", "Disney+", 26, [(5, 9900)], 5),
    ("GOOGLE*SPEAK", "Speak", 20, [(9, 29000)], 9),  # 8월 무료체험 후 9월 첫 결제
    ("네이버플러스멤버십", "Naver Plus Membership", 1, [(5, 4900)], 5),
]

# (가맹점 표기, 최소 금액, 최대 금액, 월 평균 횟수)
NOISE = [
    ("GS25 서울대점", 1200, 12000, 4),
    ("CU 봉천역점", 1000, 9000, 3),
    ("스타벅스 서울대입구역점", 4500, 13000, 3),
    ("김밥천국 낙성대점", 4000, 11000, 2),
    ("배달의민족", 13000, 32000, 2),
    ("올리브영 서울대입구점", 8000, 45000, 1),
    ("쿠팡", 9000, 60000, 2),
    ("다이소 봉천점", 2000, 15000, 1),
    ("토스페이먼츠", 5000, 50000, 1),  # 쇼핑몰 단건 결제
    ("KG이니시스", 6000, 40000, 1),
]

# UAT 시나리오 2- : 반복되지 않는 PG사 결제
FIXED_NOISE = [("KG이니시스", date(2026, 9, 7), 23170, "온라인 쇼핑몰")]


def build_rows():
    rng = random.Random(SEED)
    rows = []  # (date, merchant, amount, service, is_subscription)

    for merchant, service, day, prices, first_month in SUBSCRIPTIONS:
        for month in MONTHS:
            if month < first_month:
                continue
            charged = date(2026, month, day)
            if charged > LAST_DAY:
                continue
            amount = [p for start, p in prices if start <= month][-1]
            rows.append((charged, merchant, amount, service, True))

    # 같은 가맹점·같은 금액이 두 번 나오면 반복 결제로 오인될 수 있어 피한다.
    used = {(m, a) for _, m, a, _, _ in rows}
    for merchant, charged, amount, service in FIXED_NOISE:
        rows.append((charged, merchant, amount, service, False))
        used.add((merchant, amount))

    for merchant, low, high, per_month in NOISE:
        for month in MONTHS:
            for _ in range(rng.randint(max(0, per_month - 1), per_month + 1)):
                day = rng.randint(1, 31 if month in (5, 7, 8, 10) else 30)
                charged = date(2026, month, day)
                if charged > LAST_DAY:
                    continue
                while True:
                    amount = rng.randrange(low, high, 10)
                    if (merchant, amount) not in used:
                        break
                used.add((merchant, amount))
                rows.append((charged, merchant, amount, merchant, False))

    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def main():
    rows = build_rows()
    with open(OUT_DIR / "demo_card_2026.csv", "w", newline="", encoding="utf-8-sig") as f:
        statement = csv.writer(f)
        statement.writerow(["이용일자", "이용카드", "가맹점명", "이용금액", "승인번호"])
        with open(OUT_DIR / "demo_labels.csv", "w", newline="", encoding="utf-8") as g:
            labels = csv.writer(g)
            labels.writerow(["승인번호", "서비스", "구독여부"])
            for i, (charged, merchant, amount, service, is_sub) in enumerate(rows, start=1):
                approval = f"{30000000 + i * 7919 % 9000000:08d}"
                statement.writerow([charged.isoformat(), CARD, merchant, f"{amount:,}", approval])
                labels.writerow([approval, service, "Y" if is_sub else "N"])
    print(f"{len(rows)} rows -> {OUT_DIR / 'demo_card_2026.csv'}")


if __name__ == "__main__":
    main()
