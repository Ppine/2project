# 돈구마

> **돈구마** — 결제 내역을 분석해 **어디로 새는지 모르는 돈**을 찾아주는 서비스.
> 사람뿐 아니라 **AI 에이전트가 사용자**가 되어, 사용자 대신 지출을 조회·분석할 수 있도록 MCP 도구로 제공합니다.

서울대학교 멋쟁이사자처럼 2학기 프로젝트

## 문제 정의

- 구독 서비스가 늘면서 내가 무엇을 얼마에 구독 중인지 한눈에 파악하기 어렵다.
- 무료 체험 후 자동 전환, 잊어버린 연간 결제처럼 모르는 사이 빠져나가는 돈이 있다.
- 카드 명세서에 실제 가맹점 대신 결제대행사(PG사) 이름만 찍혀 어떤 지출인지 알 수 없는 경우가 많다.
  예: `토스페이먼츠`, `KG이니시스`, `NICE페이`, `PAYPAL *`
- 앱스토어·플레이스토어의 구독 관리 화면은 그 마켓의 인앱결제로 산 구독만 보여준다. 웹에서 카드로 직접 결제한 구독이나 외부 결제로 산 구독은 빠진다. 구독이 여러 결제 경로에 흩어져 있어 전체를 한 번에 볼 곳이 없다.
- 앱마켓 결제는 카드 명세서에 `APPLE.COM/BILL`, `GOOGLE*` 같은 한 줄로만 찍혀, 어떤 앱 구독인지 알 수 없다. PG사 표기와 같은 문제다.

## 핵심 기능

| 기능 | 하는 일 | 단계 |
| --- | --- | --- |
| 구독 탐지 | 반복 결제를 묶어 서비스명·금액·주기·다음 결제일 목록을 만든다 | MVP |
| 불분명 결제 출처 추적 | PG사·앱마켓 등 모호한 가맹점명을 실제 서비스 후보 + 신뢰도로 바꾼다 | MVP |
| 새는 돈 알림 | 무료체험 후 첫 결제, 금액 인상, 중복 구독, 안 쓰는 구독을 짚어준다 | 2차 |
| 해지 가이드 | 구독별 해지 방법·링크 안내 | 2차 |

## 서비스 구조

```
사용자 ──> AI 에이전트 (Claude, ChatGPT 등) ──> MCP 서버 ─┐
   └────> 웹 대시보드 ─────────────────────> REST API ─┤
                                                          v
                 분석 엔진: 1. 정규화·정제 → 2. 반복 결제 탐지 → 3. 출처 추론
                     │                                       │
                     v                                       v
            DB (거래 내역, 가맹점/PG사 사전)          외부 LLM API
```

MCP 도구(예시, 확정 전): `list_subscriptions`, `explain_charge`, `find_leaks`
도구 응답은 에이전트가 읽기 좋은 구조화된 JSON(서비스명, 금액, 주기, 신뢰도, 근거)으로 설계합니다.

## 데이터

마이데이터는 사용할 수 없으므로, **직접 만든 데모 데이터**로 개발하고 시연합니다.
데모 데이터는 실제 카드사 명세서와 같은 포맷으로 만들어, 실제 파일도 그대로 처리할 수 있게 합니다.

데모 데이터에 포함할 상황:

- 여러 구독이 섞인 월별 결제 (OTT, 음원, 클라우드, AI 서비스 등)
- PG사 이름이나 `APPLE.COM/BILL`, `GOOGLE*` 같은 앱마켓 묶음 표기로 찍힌 결제
- 무료체험 후 첫 결제, 금액이 오른 구독, 겹치는 구독
- 반복 결제가 아닌 일반 소비 (노이즈)
- 정답 라벨: 각 결제의 실제 서비스명과 구독 여부 (정확도 측정용)

## 개인정보 원칙

- 카드번호·계좌번호·금융사 로그인 정보는 저장하지 않는다.
- 외부 LLM에는 가맹점명·금액·날짜만 보낸다. 단, 사용자가 은행·카드앱 캡처 이미지를 올리면 거래를 읽기 위해 이미지 전체를 Gemini 로 보낸다. 캡처에 찍힌 잔액·계좌번호도 함께 넘어가므로, 이미지 업로드는 사용자가 직접 고른 경우에만 쓰고 CSV 업로드를 기본으로 안내한다.
- 에이전트는 사용자가 발급한 토큰으로 읽기 전용 접근만 한다.
- 명세서·구독 정보는 사용자마다 따로 저장하고, 다른 사용자의 데이터와 섞지 않는다.

## 기획 문서

전체 기획안: [docs/planning.md](docs/planning.md)

확장 기능 검토안: [안드로이드 자동 해지 구현 방안](docs/auto-cancellation.md) — 딥링크·화면 자동화·리버스 엔지니어링 활용과 단계별 개발 범위. 기존 분석 MVP와 별도로 검토합니다.

추가 개선 사항: [docs/improvements.md](docs/improvements.md) — Gemini 교체·업로드 형식 확장 이후 남은 과제와 우선순위.

## 로컬에서 실행하기

팀원 각자 자기 컴퓨터에서 백엔드와 프론트를 띄워 테스트하는 방법입니다. 데이터는 각자의 로컬 DB(`backend/db.sqlite3`)에만 저장되고 Git 에는 올라가지 않습니다.

### 1. 준비물

| 도구 | 버전 | 확인 명령 |
| --- | --- | --- |
| Python | 3.12 이상 | `python3 --version` |
| [uv](https://docs.astral.sh/uv/) | 최신 | `uv --version` |
| Node.js | 20 이상 | `node --version` |
| Git | - | `git --version` |

### 2. 코드 받기

```bash
git clone https://github.com/Ppine/2project.git
cd 2project
```

이미 받아 두었다면 최신 코드로 맞춥니다.

```bash
git switch main && git pull
```

### 3. 백엔드 (터미널 1)

```bash
uv venv .venv && uv pip install -p .venv -r requirements.txt
cp .env.example .env                              # 처음 한 번. 필요하면 GEMINI_API_KEY 입력 (무료)
cd backend
../.venv/bin/python manage.py migrate             # DB 만들기 / 새 마이그레이션 적용
../.venv/bin/python manage.py load_service_fees   # 구독료 표(docs/service fee modified.csv) 불러오기
../.venv/bin/python manage.py runserver           # http://127.0.0.1:8000
```

- `.env` 의 `GEMINI_API_KEY` 는 비워 둬도 됩니다. 무료 키는 [Google AI Studio](https://aistudio.google.com/apikey)에서 발급합니다. 비우면 규칙·구독료 표로만 출처를 추론하고 LLM 단계를 건너뜁니다.
- 코드를 새로 받은 뒤에는 `migrate` 를 다시 실행하세요. 구독료 표를 고쳤다면 `load_service_fees` 도 다시 실행합니다.

### 4. 프론트 (터미널 2)

```bash
cd frontend
npm install        # 처음 한 번, package.json 이 바뀌었을 때
npm run dev        # http://localhost:5173
```

브라우저에서 http://localhost:5173 을 엽니다. 프론트 개발 서버가 `/api` 요청을 백엔드(8000번)로 넘겨주므로 두 서버가 모두 켜져 있어야 합니다.
백엔드가 꺼져 있으면 저장소의 데모 명세서(`data/demo_card_2026.csv`)를 브라우저에서 바로 분석한 미리보기 화면이 뜹니다.

### 5. 화면에서 확인할 것

데모 명세서 `data/demo_card_2026.csv` 로 아래 흐름을 확인할 수 있습니다. 직접 만든 CSV 도 같은 형식(`이용일자, 이용카드, 가맹점명, 이용금액, 승인번호`)이면 올릴 수 있습니다.

1. 데모 데이터 연동 → 구독 8건, 월 합계 99,980원
2. 알림: Netflix 금액 인상, NICE페이 출처 확인
3. 내 구독 → 행을 눌러 첫 결제일·금액 이력·해지 방법 보기
4. NICE페이 행에서 실제 서비스 후보 선택 → 서비스 확인됨으로 바뀜
5. 행 상세의 "해지했어요" → 목록과 합계에서 빠지고 "해지한 구독"으로 이동, "다시 구독 중이에요"로 되돌리기
6. 가져온 명세서 → 같은 파일을 다시 올려도 결제가 두 번 저장되지 않음, 명세서 개별 삭제
7. 화면 폭을 줄여 모바일 레이아웃 확인

데모 데이터는 `python data/generate_demo.py`로 다시 만들 수 있습니다 (정답 라벨: `data/demo_labels.csv`).

형식별 시연 파일 8개(카드 1장, 카드 3장, 카드+계좌이체, 은행앱 캡처 이미지)는 [data/samples](data/samples/README.md)에 있습니다. 파일마다 확인할 거리를 적어 두었습니다. 이미지는 `GEMINI_API_KEY`가 있어야 읽힙니다.

### 6. 자동 테스트

```bash
cd backend && ../.venv/bin/pytest     # 백엔드 테스트 (외부 API 호출 없음)
cd frontend && npm run lint && npm run build   # 프론트 린트·빌드 확인
```

PR 을 올리기 전에 두 명령이 모두 통과하는지 확인해 주세요. `main` 브랜치는 보호되어 있어 직접 push 할 수 없고, PR 을 통해서만 반영됩니다.

### 7. 자주 막히는 곳

| 증상 | 해결 |
| --- | --- |
| `Error: That port is already in use` | 이미 켜진 서버가 있습니다. 그 터미널을 닫거나 `runserver 8001` 처럼 다른 포트를 씁니다 (프론트 프록시는 8000번을 보므로 가능하면 8000번을 비워 주세요) |
| 화면에 "CSV 미리보기"만 뜸 | 백엔드가 꺼져 있습니다. 터미널 1 을 확인하세요 |
| `no such table` / `no such column` | `../.venv/bin/python manage.py migrate` 를 실행하세요 |
| 구독이 하나도 안 잡힘 | `load_service_fees` 를 실행했는지 확인하세요 |
| 요청이 403 으로 거절됨 | 페이지를 새로고침한 뒤 다시 시도하세요 |
| 로컬 데이터를 처음부터 다시 | 서버를 끄고 `backend/db.sqlite3` 를 지운 뒤 3단계의 `migrate` 부터 다시 실행 |

### AI 에이전트 연결 (MCP)

토큰 발급 방법은 팀 내부 안내를 따릅니다. 토큰은 발급할 때 한 번만 출력되므로 바로 복사해 두세요.

Claude Desktop의 `claude_desktop_config.json`에 추가 (경로는 본인 환경에 맞게):

```json
{
  "mcpServers": {
    "dongguma": {
      "command": "/절대경로/2project/.venv/bin/python",
      "args": ["/절대경로/2project/mcp_server/server.py"],
      "env": {
        "DONGGUMA_API_URL": "http://127.0.0.1:8000/api",
        "DONGGUMA_TOKEN": "발급받은 토큰"
      }
    }
  }
}
```

| MCP 도구 | 역할 |
| --- | --- |
| `list_subscriptions()` | 구독 목록, 월 합계, 다음 결제일 |
| `explain_charge(merchant, amount)` | 결제 한 건의 실제 서비스 후보 + 신뢰도 + 근거 |
