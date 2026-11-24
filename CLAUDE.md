# 돈구마 — Claude 작업 안내

## 작업 전에 항상 읽기

- [docs/planning.md](docs/planning.md): 서비스 기획과 확정된 정책(UAT 반영분 포함). 기능을 바꾸기 전에 관련 정책과 열린 질문을 확인한다.
- [docs/improvements.md](docs/improvements.md): 남은 개선 항목, 우선순위(P0~P2), 진행 현황. 작업이 어느 항목에 해당하는지 먼저 찾는다.

정책과 다른 방향으로 고쳐야 하거나, 열린 질문(`- [ ]`)에 걸린 작업이면 진행 전에 사용자에게 묻는다.

## 작업 후에 갱신하기

- improvements.md 항목을 끝냈으면 진행 현황 표의 상태를 바꾼다(☐ → ◐ 일부 / ☑ 완료, 남은 일은 한 줄로).
- 작업 중 새로 발견한 문제는 근거(파일·함수, 재현 방법)와 함께 improvements.md 에 새 번호로 추가한다.
- 정책을 정하거나 바꿨으면 planning.md 의 해당 절을 고치고, 열린 질문은 체크하고 결정 내용을 적는다.
- 새 UAT 피드백 문서가 `docs/`에 들어오면 planning.md 에 "UAT 피드백 반영 (날짜)" 절을, improvements.md 에 구현 항목을 같은 형식으로 추가한다.

## 프로젝트 구조

- `frontend/` React + Vite (`npm run dev`, `/api`는 `127.0.0.1:8000`으로 프록시). 백엔드 없이도 오프라인 데모로 화면을 볼 수 있다.
- `backend/` Django. 분석 엔진은 `backend/analysis/`(parsers → clean → detect → infer), API 는 `backend/ledger/`.
- `mcp_server/`, `mobile/`, `data/`(데모·샘플 명세서).
