"""시연용 테스트 명세서 8개(4가지 형식 × 2)를 만든다.

    uv run --with pillow python data/samples/generate_samples.py

출력 (data/samples/):
    1_card_single_a.csv, 1_card_single_b.csv        카드 1장 명세서 (이용일자, 이용카드, 가맹점명, 이용금액, 승인번호)
    2_card_multi_a.csv,  2_card_multi_b.csv         카드 3장이 섞인 명세서 (같은 머리글, 이용카드만 다름)
    3_card_transfer_a.csv, 3_card_transfer_b.csv    카드 결제 + 계좌이체가 섞인 지출 내역 (거래일자, 구분, 결제수단, 내용, 금액, 메모)
    4_bank_capture_a.png, 4_bank_capture_b.png      은행앱 거래내역 긴 캡처 (입금 포함 — 지출만 읽혀야 한다)

금액은 docs/service fee modified.csv 의 실제 요금을 쓴다. 각 파일이 노리는 시나리오는 data/samples/README.md 참고.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# ── 공통 ────────────────────────────────────────────────────────────────


def month_range(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def safe_date(y, m, d):
    while True:
        try:
            return date(y, m, d)
        except ValueError:
            d -= 1


def build(subs, noise, start, end, last_day, seed, card_for=None):
    """subs: (가맹점, 결제일, [(시작(y,m), 금액)], 첫 결제(y,m), 마지막 결제(y,m)|None, 카드키)
    noise: (가맹점, 최소, 최대, 월 평균 횟수, 카드키)
    반환: [(date, 가맹점, 금액, 카드키)] 날짜순"""
    rng = random.Random(seed)
    rows = []
    for merchant, day, prices, first, last, card in subs:
        for y, m in month_range(start, end):
            if (y, m) < first or (last and (y, m) > last):
                continue
            charged = safe_date(y, m, day)
            if charged > last_day:
                continue
            amount = [p for s, p in prices if s <= (y, m)][-1]
            rows.append((charged, merchant, amount, card(y, m) if callable(card) else card))
    used = {(r[1], r[2]) for r in rows}
    for merchant, low, high, per_month, card in noise:
        for y, m in month_range(start, end):
            for _ in range(rng.randint(max(0, per_month - 1), per_month + 1)):
                charged = safe_date(y, m, rng.randint(1, 31))
                if charged > last_day:
                    continue
                while True:  # 같은 가맹점·같은 금액이 두 번 나오면 반복 결제로 오인되므로 피한다
                    amount = rng.randrange(low, high, 10)
                    if (merchant, amount) not in used:
                        break
                used.add((merchant, amount))
                rows.append((charged, merchant, amount, card))
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def write_card_csv(name, rows, cards, seed):
    rng = random.Random(seed)
    with open(OUT_DIR / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["이용일자", "이용카드", "가맹점명", "이용금액", "승인번호"])
        for charged, merchant, amount, card in rows:
            w.writerow([charged.isoformat(), cards[card], merchant, f"{amount:,}", f"{rng.randrange(10**7, 10**8)}"])
    print(f"{len(rows):4d}건 -> {name}")


# ── 1. 카드 1장 ─────────────────────────────────────────────────────────

COMMON_NOISE = [
    ("GS25 서울대점", 1200, 12000, 4, "A"),
    ("CU 봉천역점", 1000, 9000, 3, "A"),
    ("스타벅스 서울대입구역점", 4500, 13000, 3, "A"),
    ("배달의민족", 13000, 32000, 2, "A"),
    ("쿠팡", 9000, 60000, 2, "A"),
    ("KG이니시스", 6000, 40000, 1, "A"),  # 반복되지 않는 PG 단건 결제
]


def single_a():
    """대학생: 무료체험 후 첫 결제(CLASS101), 앱마켓·PG 표기, 학생 요금."""
    subs = [
        ("NETFLIX.COM", 5, [((2026, 4), 7000)], (2026, 4), None, "A"),
        ("NHN KCP*티빙", 12, [((2026, 4), 9500)], (2026, 4), None, "A"),
        ("GOOGLE*YOUTUBE", 18, [((2026, 4), 14900)], (2026, 4), None, "A"),
        ("PAYPAL *SPOTIFY", 21, [((2026, 4), 6600)], (2026, 4), None, "A"),
        ("배민클럽", 2, [((2026, 4), 3990)], (2026, 4), None, "A"),
        ("토스페이먼츠", 27, [((2026, 7), 19000)], (2026, 7), None, "A"),  # 6월 무료체험 → 7월 첫 결제 (CLASS101+)
    ]
    noise = COMMON_NOISE + [("후불교통 서울", 1450, 1700, 1, "A"), ("김밥천국 낙성대점", 4000, 11000, 2, "A")]
    rows = build(subs, noise, (2026, 4), (2026, 9), date(2026, 9, 30), seed=101)
    write_card_csv("1_card_single_a.csv", rows, {"A": "본인 5310-71**-****-1187"}, seed=101)


def single_b():
    """직장인: 금액 인상(Disney+), 같은 APPLE.COM/BILL 아래 두 구독, 음원 중복(Apple Music + Spotify)."""
    subs = [
        ("APPLE.COM/BILL", 3, [((2026, 5), 14000)], (2026, 5), None, "A"),  # iCloud+ 2TB
        ("APPLE.COM/BILL", 9, [((2026, 5), 8900)], (2026, 5), None, "A"),  # Apple Music
        ("PAYPAL *SPOTIFY", 14, [((2026, 5), 11990)], (2026, 5), None, "A"),
        ("디즈니플러스", 19, [((2026, 5), 9900), ((2026, 8), 13900)], (2026, 5), None, "A"),  # Disney+ 스탠다드 → 프리미엄 (직접 결제라 한 구독의 금액 변동으로 묶임)
        ("MICROSOFT*365", 23, [((2026, 5), 12500)], (2026, 5), None, "A"),
        ("밀리의서재", 28, [((2026, 5), 11900)], (2026, 5), None, "A"),
        ("ADOBE *PHOTOGPHY", 11, [((2026, 5), 26400)], (2026, 5), (2026, 8), "A"),  # 8월 이후 해지
    ]
    noise = [
        ("이마트24 역삼점", 1500, 15000, 4, "A"),
        ("투썸플레이스 강남역점", 4800, 14000, 3, "A"),
        ("카카오T 택시", 6000, 28000, 3, "A"),
        ("요기요", 14000, 38000, 2, "A"),
        ("교보문고 강남점", 12000, 45000, 1, "A"),
        ("토스페이먼츠", 5000, 70000, 2, "A"),
        ("SSG.COM", 15000, 90000, 1, "A"),
    ]
    rows = build(subs, noise, (2026, 5), (2026, 10), date(2026, 10, 31), seed=102)
    write_card_csv("1_card_single_b.csv", rows, {"A": "본인 4092-33**-****-6620"}, seed=102)


# ── 2. 카드 3장 ─────────────────────────────────────────────────────────

THREE_CARDS_A = {
    "S": "본인 4518-44**-****-2201 (신한 체크)",
    "K": "본인 9490-12**-****-7730 (KB국민 신용)",
    "H": "본인 4330-90**-****-5512 (현대 신용)",
}


def multi_a():
    """카드 3장: 구독이 카드별로 흩어짐, 중간에 결제 카드를 바꾼 구독(Netflix), 카드 간 중복 구독(YouTube)."""
    subs = [
        ("NETFLIX.COM", 7, [((2026, 4), 13500)], (2026, 4), None, lambda y, m: "K" if m < 7 else "H"),  # 7월부터 현대카드로
        ("GOOGLE*YOUTUBE", 15, [((2026, 4), 14900)], (2026, 4), None, "S"),
        ("APPLE.COM/BILL", 15, [((2026, 6), 14900)], (2026, 6), None, "H"),  # 다른 카드로 YouTube Premium 을 iOS 에서 또 결제
        ("쿠팡(와우멤버십)", 10, [((2026, 4), 7890)], (2026, 4), None, "K"),
        ("네이버플러스멤버십", 1, [((2026, 4), 4900)], (2026, 4), None, "S"),
        ("GOOGLE*GEMINI", 24, [((2026, 8), 29000)], (2026, 8), None, "H"),  # Google AI Pro, 8월 신규
    ]
    noise = [
        ("GS25 신림점", 1200, 12000, 3, "S"),
        ("메가MGC커피 신림역점", 1500, 6500, 4, "S"),
        ("후불교통 서울", 1450, 1700, 1, "S"),
        ("배달의민족", 13000, 32000, 2, "K"),
        ("쿠팡", 9000, 60000, 2, "K"),
        ("올리브영 신림점", 8000, 45000, 1, "H"),
        ("무신사", 29000, 120000, 1, "H"),
        ("CGV 신림", 12000, 30000, 1, "H"),
        ("KG이니시스", 6000, 40000, 1, "K"),
    ]
    rows = build(subs, noise, (2026, 4), (2026, 9), date(2026, 9, 30), seed=201)
    write_card_csv("2_card_multi_a.csv", rows, THREE_CARDS_A, seed=201)


def multi_b():
    """카드 3장: 같은 금액의 PG 결제가 후보 2개(NICE페이 13,900원 = Wavve 프리미엄 / Disney+ 프리미엄), 연간 결제."""
    cards = {
        "W": "본인 5365-10**-****-0981 (우리 체크)",
        "M": "본인 5107-37**-****-4416 (삼성 신용)",
        "L": "가족 9410-61**-****-2093 (롯데 신용)",
    }
    subs = [
        ("NICE페이", 6, [((2026, 5), 13900)], (2026, 5), None, "M"),
        ("NETFLIX.COM", 20, [((2026, 5), 17000)], (2026, 5), None, "L"),
        ("카카오", 13, [((2026, 5), 3900)], (2026, 5), None, "W"),  # 이모티콘 플러스 웹 구독
        ("GOOGLE*DUOLINGO", 2, [((2026, 6), 129000)], (2026, 6), (2026, 6), "M"),  # 연간 1회 — 반복으로 안 잡히는 게 정상
        ("왓챠", 25, [((2026, 5), 7900)], (2026, 5), None, "W"),
        ("PAYPAL *CANVA", 17, [((2026, 7), 9900)], (2026, 7), None, "M"),
    ]
    noise = [
        ("세븐일레븐 마포점", 1300, 11000, 3, "W"),
        ("파리바게뜨 합정점", 3000, 18000, 2, "W"),
        ("홈플러스 합정점", 20000, 110000, 2, "L"),
        ("쿠팡이츠", 12000, 35000, 3, "M"),
        ("카카오T 택시", 5000, 25000, 2, "M"),
        ("다이소 홍대점", 2000, 15000, 1, "W"),
        ("토스페이먼츠", 5000, 60000, 2, "L"),
    ]
    rows = build(subs, noise, (2026, 5), (2026, 10), date(2026, 10, 31), seed=202)
    write_card_csv("2_card_multi_b.csv", rows, cards, seed=202)


# ── 3. 카드 + 계좌이체 ─────────────────────────────────────────────────


def write_mixed_csv(name, rows, methods, seed):
    """methods: 키 -> (구분, 결제수단 표기). 금액은 지출만, 양수."""
    rng = random.Random(seed)
    with open(OUT_DIR / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["거래일자", "구분", "결제수단", "내용", "금액", "메모"])
        for charged, merchant, amount, key in rows:
            kind, method = methods[key]
            memo = rng.choice(["", "", "", "생활비", "고정비"]) if kind != "카드결제" else ""
            w.writerow([charged.strftime("%Y.%m.%d"), kind, method, merchant, f"{amount:,}", memo])
    print(f"{len(rows):4d}건 -> {name}")


def mixed_a():
    """자취생: 월세·통신비·보험이 자동/계좌이체로, 구독은 카드로. 친구 더치페이 이체(노이즈)."""
    methods = {
        "C": ("카드결제", "신한 체크 2201"),
        "D": ("카드결제", "KB국민 신용 7730"),
        "T": ("계좌이체", "신한 입출금 ***-***-118204"),
        "A": ("자동이체", "신한 입출금 ***-***-118204"),
    }
    subs = [
        ("월세 김OO", 25, [((2026, 4), 450000)], (2026, 4), None, "T"),
        ("SKT 통신요금", 21, [((2026, 4), 49000)], (2026, 4), None, "A"),
        ("삼성화재 보험료", 10, [((2026, 4), 32800)], (2026, 4), None, "A"),
        ("멜론 정기결제", 16, [((2026, 4), 10900)], (2026, 4), None, "A"),  # 구독료 표에 없음 → LLM 추론 대상
        ("NETFLIX.COM", 7, [((2026, 4), 13500)], (2026, 4), None, "D"),
        ("GOOGLE*YOUTUBE", 15, [((2026, 4), 14900)], (2026, 4), None, "C"),
        ("쿠팡(와우멤버십)", 10, [((2026, 4), 7890)], (2026, 4), None, "D"),
    ]
    noise = [
        ("GS25 서울대점", 1200, 12000, 4, "C"),
        ("스타벅스 서울대입구역점", 4500, 13000, 2, "C"),
        ("배달의민족", 13000, 32000, 2, "D"),
        ("쿠팡", 9000, 60000, 2, "D"),
        ("이체 박OO", 8000, 40000, 2, "T"),  # 더치페이
        ("이체 이OO", 5000, 30000, 1, "T"),
        ("관리비", 70000, 130000, 1, "A"),  # 매달 금액이 달라 반복 결제로 안 잡힘
    ]
    rows = build(subs, noise, (2026, 4), (2026, 9), date(2026, 9, 30), seed=301)
    write_mixed_csv("3_card_transfer_a.csv", rows, methods, seed=301)


def mixed_b():
    """직장인: 인터넷·헬스장·정기후원 자동이체, 통신비 요금제 변경, 구독은 카드 2장."""
    methods = {
        "C": ("카드결제", "현대 신용 5512"),
        "D": ("카드결제", "우리 체크 0981"),
        "T": ("계좌이체", "우리 입출금 ***-****-2207"),
        "A": ("자동이체", "우리 입출금 ***-****-2207"),
    }
    subs = [
        ("KT 통신요금", 25, [((2026, 5), 69000), ((2026, 8), 55000)], (2026, 5), None, "A"),  # 8월 요금제 변경
        ("LG U+ 인터넷", 18, [((2026, 5), 33000)], (2026, 5), None, "A"),
        ("에이블짐 회비", 1, [((2026, 5), 59000)], (2026, 5), None, "T"),
        ("유니세프 정기후원", 20, [((2026, 5), 30000)], (2026, 5), None, "A"),
        ("APPLE.COM/BILL", 4, [((2026, 5), 4400)], (2026, 5), None, "C"),  # iCloud+ 200GB
        ("토스페이먼츠", 12, [((2026, 5), 10900)], (2026, 5), None, "D"),  # Wavve 스탠다드
        ("CHATGPT SUBSCRIPTION", 8, [((2026, 6), 29000)], (2026, 6), None, "C"),  # USD 결제 원화 환산
    ]
    noise = [
        ("이마트24 여의도점", 1500, 15000, 4, "D"),
        ("폴바셋 여의도점", 5000, 14000, 3, "C"),
        ("카카오T 택시", 6000, 28000, 2, "C"),
        ("요기요", 14000, 38000, 2, "D"),
        ("이체 최OO", 10000, 100000, 1, "T"),
        ("도시가스 요금", 18000, 65000, 1, "A"),  # 매달 금액이 다름
    ]
    rows = build(subs, noise, (2026, 5), (2026, 10), date(2026, 10, 31), seed=302)
    write_mixed_csv("3_card_transfer_b.csv", rows, methods, seed=302)


# ── 4. 은행앱 캡처 이미지 ──────────────────────────────────────────────

FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS
    "C:/Windows/Fonts/malgun.ttf",  # Windows
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # Linux
]
WEEKDAYS = "월화수목금토일"


def _font(size, bold=False):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        if Path(path).exists():
            if path.endswith(".ttc"):  # AppleSDGothicNeo: 0=Regular, 6=Bold
                return ImageFont.truetype(path, size, index=6 if bold else 0)
            return ImageFont.truetype(path, size)
    raise SystemExit("한글 폰트를 찾을 수 없습니다. FONT_CANDIDATES 에 경로를 추가하세요.")


def capture_rows(subs, noise, deposits, start, end, last_day, seed, opening):
    """[(date, 이름, 부가설명, 금액(입금 +, 출금 -), 잔액)] 최신순."""
    spend = build(subs, noise, start, end, last_day, seed)
    rng = random.Random(seed)
    items = [(d, m, kind, -a) for d, m, a, kind in spend]
    for name, day, amount in deposits:
        for y, mo in month_range(start, end):
            d = safe_date(y, mo, day)
            if d <= last_day:
                items.append((d, name, "입금", amount))
    items.sort(key=lambda r: r[0])
    balance, out = opening, []
    for d, name, kind, amount in items:
        balance += amount
        t = f"{rng.randint(7, 23):02d}:{rng.randint(0, 59):02d}"
        out.append((d, name, f"{kind} · {t}", amount, balance))
    return list(reversed(out))


def draw_capture(name, title, account, rows, dark):
    from PIL import Image, ImageDraw

    W, PAD = 720, 32
    bg, card, fg, sub, line = (
        ((18, 18, 20), (28, 28, 32), (240, 240, 245), (140, 140, 150), (45, 45, 52))
        if dark
        else ((242, 244, 246), (255, 255, 255), (25, 31, 40), (139, 149, 161), (234, 236, 239))
    )
    minus, plus = ((240, 240, 245), (90, 160, 255)) if dark else ((25, 31, 40), (49, 130, 246))
    f_title, f_big, f_hdr = _font(30, True), _font(44, True), _font(24, True)
    f_name, f_sub, f_amt, f_bal = _font(28), _font(21), _font(28, True), _font(20)

    # 높이 계산
    days = []
    for r in rows:
        if not days or days[-1][0] != r[0]:
            days.append((r[0], []))
        days[-1][1].append(r)
    months = {(d.year, d.month) for d, _ in days}
    H = 330 + len(days) * 58 + len(rows) * 104 + len(months) * 70 + 80
    img = Image.new("RGB", (W, H), bg)
    g = ImageDraw.Draw(img)

    # 상태바 + 계좌 요약
    g.text((PAD, 20), "9:41", font=_font(24, True), fill=fg)
    g.text((W - PAD - 110, 20), "5G  100%", font=_font(22), fill=fg)
    g.text((PAD, 80), "‹", font=_font(40), fill=fg)
    g.text((W // 2, 88), title, font=f_title, fill=fg, anchor="mt")
    g.rounded_rectangle((PAD - 8, 150, W - PAD + 8, 300), 24, fill=card)
    g.text((PAD + 16, 172), account, font=f_sub, fill=sub)
    g.text((PAD + 16, 210), f"{rows[0][4]:,}원", font=f_big, fill=fg)
    g.text((W - PAD - 16, 270), "전체 · 최신순", font=f_sub, fill=sub, anchor="rs")

    y, cur_month = 330, None
    for d, items in days:
        if (d.year, d.month) != cur_month:
            cur_month = (d.year, d.month)
            g.text((PAD, y + 18), f"{d.year}년 {d.month}월", font=_font(30, True), fill=fg)
            y += 70
        g.text((PAD, y + 18), f"{d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일", font=f_hdr, fill=sub)
        y += 58
        for _, nm, desc, amount, bal in items:
            cx, cy = PAD + 30, y + 50
            color = plus if amount > 0 else (120, 130, 145)
            g.ellipse((cx - 30, cy - 30, cx + 30, cy + 30), fill=line)
            g.text((cx, cy), nm[0], font=f_hdr, fill=color, anchor="mm")
            g.text((PAD + 80, y + 22), nm, font=f_name, fill=fg)
            g.text((PAD + 80, y + 60), desc, font=f_sub, fill=sub)
            sign = "+" if amount > 0 else "-"
            g.text((W - PAD, y + 22), f"{sign}{abs(amount):,}원", font=f_amt,
                   fill=plus if amount > 0 else minus, anchor="ra")
            g.text((W - PAD, y + 62), f"{bal:,}원", font=f_bal, fill=sub, anchor="ra")
            y += 104
        g.line((PAD, y + 4, W - PAD, y + 4), fill=line, width=2)
    img = img.crop((0, 0, W, y + 60))
    img.save(OUT_DIR / name, optimize=True)
    print(f"{len(rows):4d}건 -> {name} ({img.width}x{img.height})")


def capture_a():
    """밝은 테마 입출금통장 캡처: 체크카드 결제 + 자동이체 + 입금(급여·용돈)."""
    subs = [
        ("NETFLIX.COM", 7, [((2026, 8), 13500)], (2026, 8), None, "체크카드"),
        ("GOOGLE*YOUTUBE", 15, [((2026, 8), 14900)], (2026, 8), None, "체크카드"),
        ("SKT 통신요금", 21, [((2026, 8), 49000)], (2026, 8), None, "자동이체"),
        ("NICE페이", 26, [((2026, 8), 9900)], (2026, 8), None, "체크카드"),
    ]
    noise = [
        ("GS25 서울대점", 1200, 9000, 2, "체크카드"),
        ("스타벅스 서울대입구역점", 4500, 9000, 1, "체크카드"),
        ("배달의민족", 15000, 28000, 1, "체크카드"),
        ("이체 박OO", 8000, 30000, 1, "이체"),
    ]
    deposits = [("아르바이트 급여", 10, 820000), ("용돈 엄마", 1, 300000)]
    rows = capture_rows(subs, noise, deposits, (2026, 8), (2026, 10), date(2026, 10, 28), 401, 640000)
    draw_capture("4_bank_capture_a.png", "거래내역", "구마은행 입출금통장 ***-****-3381", rows, dark=False)


def capture_b():
    """어두운 테마 캡처: 다른 은행앱 스타일, 앱마켓 결제 2건(같은 표기·다른 금액), 월세 이체."""
    subs = [
        ("APPLE.COM/BILL", 3, [((2026, 9), 4400)], (2026, 9), None, "체크카드"),
        ("APPLE.COM/BILL", 18, [((2026, 9), 8900)], (2026, 9), None, "체크카드"),
        ("쿠팡(와우멤버십)", 10, [((2026, 9), 7890)], (2026, 9), None, "체크카드"),
        ("월세 김OO", 25, [((2026, 9), 450000)], (2026, 9), None, "이체"),
        ("토스페이먼츠", 12, [((2026, 9), 19000)], (2026, 9), None, "체크카드"),  # CLASS101+
    ]
    noise = [
        ("CU 봉천역점", 1000, 8000, 2, "체크카드"),
        ("메가MGC커피 낙성대점", 1500, 6500, 2, "체크카드"),
        ("쿠팡", 9000, 45000, 1, "체크카드"),
    ]
    deposits = [("월급 (주)구마컴퍼니", 25, 2350000)]
    rows = capture_rows(subs, noise, deposits, (2026, 9), (2026, 11), date(2026, 11, 5), 402, 1180000)
    draw_capture("4_bank_capture_b.png", "입출금 내역", "OO뱅크 입출금 ***-***-7745", rows, dark=True)


if __name__ == "__main__":
    single_a()
    single_b()
    multi_a()
    multi_b()
    mixed_a()
    mixed_b()
    capture_a()
    capture_b()
