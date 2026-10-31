import { useEffect, useMemo, useState } from "react";
import demoCsv from "../../data/demo_card_2026.csv?raw";

const CYCLE_LABELS = { monthly: "월", yearly: "연" };
const CONFIDENCE_LABELS = {
  high: "높은 신뢰도",
  medium: "확인 필요",
  low: "확인 필요",
};
const won = (n) => `${Number(n ?? 0).toLocaleString("ko-KR")}원`;

const LOCAL_SERVICES = [
  {
    merchant: "네이버플러스멤버십",
    service: "Naver Plus Membership",
    plan: "멤버십",
    cancel: { via: "web", url: "https://nid.naver.com/membership/my" },
  },
  {
    merchant: "NETFLIX.COM",
    service: "Netflix",
    plan: "스탠다드",
    cancel: { via: "web", url: "https://help.netflix.com/en/node/407" },
  },
  {
    merchant: "APPLE.COM/BILL",
    service: "iCloud+",
    plan: "200GB",
    cancel: {
      via: "app_store",
      url: "https://apps.apple.com/account/subscriptions",
    },
  },
  {
    merchant: "쿠팡(와우멤버십)",
    service: "Coupang Wow",
    plan: "와우 멤버십",
    cancel: { via: "web", url: "https://www.coupang.com/np/coupangwow" },
  },
  {
    merchant: "GOOGLE*SPEAK",
    service: "Speak",
    plan: "프리미엄",
    cancel: {
      via: "google_play",
      url: "https://play.google.com/store/account/subscriptions",
    },
  },
  {
    merchant: "PAYPAL *SPOTIFY",
    service: "Spotify",
    plan: "Premium",
    cancel: {
      via: "web",
      url: "https://www.spotify.com/account/subscription/",
    },
  },
  {
    merchant: "토스페이먼츠",
    amount: 14900,
    service: "YouTube Premium",
    plan: "Premium",
    cancel: { via: "web", url: "https://www.youtube.com/paid_memberships" },
  },
  {
    merchant: "NICE페이",
    amount: 9900,
    service: "NICE페이",
    confidence: "medium",
    candidates: ["Disney+", "Canva", "CapCut"],
  },
];

function parseCsvLine(line) {
  return line
    .split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/)
    .map((value) => value.trim().replace(/^"|"$/g, "").replaceAll('""', '"'));
}

function makeLocalDemo(csv) {
  const [headerLine, ...lines] = csv
    .replace(/^\uFEFF/, "")
    .trim()
    .split(/\r?\n/);
  const headers = parseCsvLine(headerLine);
  const rows = lines.map((line) =>
    Object.fromEntries(
      parseCsvLine(line).map((value, index) => [headers[index], value]),
    ),
  );
  const transactions = rows.map((row) => ({
    date: row["이용일자"],
    merchant: row["가맹점명"],
    amount: Number(row["이용금액"].replaceAll(",", "")),
  }));

  const subscriptions = LOCAL_SERVICES.flatMap((definition) => {
    const charges = transactions.filter(
      (item) =>
        item.merchant === definition.merchant &&
        (!definition.amount || item.amount === definition.amount),
    );
    if (charges.length < 2) return [];
    const last = charges.at(-1);
    const [year, month, day] = last.date.split("-").map(Number);
    const nextDate = new Date(Date.UTC(year, month, day));
    const confidence = definition.confidence || "high";
    return [
      {
        service: definition.service,
        merchant: definition.merchant,
        amount: last.amount,
        cycle: "monthly",
        next_payment_date: nextDate.toISOString().slice(0, 10),
        confidence,
        candidates: (definition.candidates || [definition.service]).map(
          (service) => ({ service, confidence }),
        ),
        price_history: [...new Set(charges.map((charge) => charge.amount))].map(
          (amount) => ({ amount }),
        ),
        plan: definition.plan,
        cancel: definition.cancel,
      },
    ];
  }).sort((a, b) => a.next_payment_date.localeCompare(b.next_payment_date));

  return {
    transactions: transactions.length,
    monthly_total: subscriptions.reduce(
      (total, item) => total + item.amount,
      0,
    ),
    subscriptions,
  };
}

const LOCAL_DEMO = makeLocalDemo(demoCsv);
const dateLabel = (value) => {
  if (!value) return "일정 확인 중";
  const date = new Date(`${value}T00:00:00`);
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
};

function App() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [offlineDemo, setOfflineDemo] = useState(false);
  const [screen, setScreen] = useState(() =>
    window.localStorage.getItem("dongguma-demo-connected") === "true"
      ? "dashboard"
      : "onboarding",
  );
  const [connecting, setConnecting] = useState(false);
  const [connectStep, setConnectStep] = useState(0);
  const [sourceName, setSourceName] = useState("demo_card_2026.csv");

  async function postStatement(file) {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/statements/", {
      method: "POST",
      body,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok)
      throw new Error(data.detail ?? "명세서를 분석하지 못했어요.");
    return data;
  }

  async function loadDemo() {
    setLoading(true);
    setError("");
    setSourceName("demo_card_2026.csv");
    try {
      const data = await postStatement(
        new File([demoCsv], "demo_card_2026.csv", { type: "text/csv" }),
      );
      setOfflineDemo(false);
      setResult(data);
    } catch (e) {
      // 백엔드 미실행 상태에서도 프론트 데모를 바로 볼 수 있도록 로컬 예시를 표시합니다.
      setOfflineDemo(true);
      setResult(LOCAL_DEMO);
      setError("");
    } finally {
      setLoading(false);
    }
  }

  async function uploadStatement(file) {
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const data = await postStatement(file);
      setOfflineDemo(false);
      setSourceName(file.name);
      setResult(data);
    } catch (e) {
      // 직접 올린 파일은 로컬 데모로 대체하지 않고 실패 이유를 보여줍니다.
      setError(
        e instanceof TypeError
          ? "백엔드에 연결하지 못했어요. 서버가 켜져 있는지 확인해 주세요."
          : e.message,
      );
    } finally {
      setLoading(false);
    }
  }

  async function connectDemo() {
    if (connecting) return;
    setConnecting(true);
    setConnectStep(0);
    for (let step = 1; step <= 3; step += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 850));
      setConnectStep(step);
    }
    await loadDemo();
    window.localStorage.setItem("dongguma-demo-connected", "true");
    setScreen("dashboard");
    setConnecting(false);
  }

  useEffect(() => {
    if (screen === "dashboard" && !result) loadDemo();
  }, [screen]);

  if (screen === "onboarding")
    return (
      <Onboarding
        connecting={connecting}
        step={connectStep}
        onConnect={connectDemo}
      />
    );

  const subscriptions = result?.subscriptions ?? [];
  const needsReview = subscriptions.filter(
    (s) => s.confidence !== "high",
  ).length;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="돈구마 홈">
          <span className="brand-mark">
            <img className="brand-logo-image" src="/dongguma-logo.svg" alt="" />
          </span>
          <span>돈구마</span>
        </a>
        <div className="side-label">관리</div>
        <nav className="side-nav" aria-label="메인 메뉴">
          <a className="nav-item active" href="#overview">
            <span className="nav-icon">▦</span>한눈에 보기
          </a>
          <a className="nav-item" href="#subscriptions">
            <span className="nav-icon">◷</span>내 구독
          </a>
          <a className="nav-item" href="#insights">
            <span className="nav-icon">⌁</span>새는 돈 알림
          </a>
        </nav>
        <div className="sidebar-bottom">
          <div className="demo-side-card">
            <span className="demo-dot" />
            데모 계정
            <p>
              가상 결제 내역을 바탕으로
              <br />
              서비스를 둘러보고 있어요.
            </p>
          </div>
          <div className="profile-row">
            <span className="avatar avatar-mascot">
              <img src="/dongguma-logo.svg" alt="" />
            </span>
            <span>
              <b>don_gu_miner</b>
              <small>체험 계정</small>
            </span>
            <span className="more">···</span>
          </div>
        </div>
      </aside>

      <main className="main-area" id="top">
        <header className="topbar">
          <div className="breadcrumb">
            내 금융 <span>/</span> 구독 관리
          </div>
          <div className="top-actions">
            <button
              className="replay-onboarding"
              type="button"
              onClick={async () => {
                // 후보 선택 결과(서버에 저장된 매핑)도 지워 처음 상태로 되돌립니다.
                await fetch("/api/merchant-aliases/", {
                  method: "DELETE",
                }).catch(() => {});
                window.localStorage.removeItem("dongguma-demo-connected");
                setResult(null);
                setOfflineDemo(false);
                setError("");
                setScreen("onboarding");
              }}
            >
              연동 과정 다시 보기
            </button>
            <span className="demo-pill">
              <span className="demo-dot" />
              데모 데이터
            </span>
            <button className="icon-button" type="button" aria-label="알림">
              ♧<i />
            </button>
          </div>
        </header>

        <div className="page-content" id="overview">
          <section className="welcome-row">
            <div className="hero-copy">
              <h1>돈구마</h1>
              <p className="welcome-copy">
                <strong className="hero-quote">“땅 파서 돈이 나오냐?”</strong>{" "}
                돈구마는 결제 땅에서 숨은 돈을 캐낼 수 있습니다!
              </p>
            </div>
            <div className="hero-side">
              <div className="mascot-stage">
                <img
                  className="mascot-image"
                  src="/dongguma-mascot-2d.png"
                  alt="돈구마가 호미로 땅을 파서 동전과 지폐를 발견하고 기뻐하는 모습"
                />
              </div>
              <div className="hero-actions">
                <label
                  className={`refresh-button upload-button${loading ? " disabled" : ""}`}
                >
                  <input
                    type="file"
                    accept=".csv"
                    disabled={loading}
                    onChange={(e) => {
                      uploadStatement(e.target.files?.[0]);
                      e.target.value = "";
                    }}
                  />
                  <span>⇪</span> 내 명세서 올리기
                </label>
                <button
                  className="refresh-button"
                  type="button"
                  onClick={loadDemo}
                  disabled={loading}
                >
                  <span className={loading ? "spin" : ""}>↻</span> 데모 다시 찾기
                </button>
              </div>
            </div>
          </section>

          {offlineDemo && (
            <div className="error-panel offline-panel" role="status">
              <b>CSV 미리보기</b>
              <span>
                백엔드 연결 전이라 저장소의 demo_card_2026.csv를 브라우저에서
                분석해 보여드려요.
              </span>
            </div>
          )}
          {error && (
            <div className="error-panel" role="alert">
              <b>데이터를 불러오지 못했어요</b>
              <span>{error}</span>
              <button type="button" onClick={loadDemo}>
                데모 데이터 보기
              </button>
            </div>
          )}

          {loading && !result ? (
            <LoadingState />
          ) : (
            result && (
              <>
                <section className="summary-grid" aria-label="구독 요약">
                  <article className="summary-card primary-summary">
                    <div className="summary-label">
                      매달 나가는 구독료 <span className="mini-icon">₩</span>
                    </div>
                    <strong>{won(result.monthly_total)}</strong>
                    <div className="summary-foot">
                      <span className="trend-icon">↗</span> 월 기준 예상 지출
                    </div>
                    <div className="summary-decoration" aria-hidden="true">
                      ₩
                    </div>
                  </article>
                  <article className="summary-card">
                    <div className="summary-label">
                      찾은 구독 <span className="mini-icon blue-icon">◷</span>
                    </div>
                    <strong>
                      {subscriptions.length}
                      <small>건</small>
                    </strong>
                    <div className="summary-foot">여러 결제처에서 모았어요</div>
                  </article>
                  <article className="summary-card coral-summary">
                    <div className="summary-label">
                      확인할 항목{" "}
                      <span className="mini-icon coral-icon">!</span>
                    </div>
                    <strong>
                      {needsReview}
                      <small>건</small>
                    </strong>
                    <div className="summary-foot">
                      실제 서비스를 확인해 주세요
                    </div>
                  </article>
                </section>

                <section className="insight-banner" id="insights">
                  <div className="insight-symbol">✦</div>
                  <div className="insight-copy">
                    <span className="insight-kicker">이번 달 체크</span>
                    <h2>
                      {needsReview > 0
                        ? `정체를 확인할 결제가 ${needsReview}건 있어요`
                        : "모든 결제 출처를 확인했어요"}
                    </h2>
                    <p>
                      PG사와 앱마켓 이름으로 표시된 결제는 실제 서비스 후보를
                      확인해 보세요.
                    </p>
                  </div>
                  <a href="#subscriptions" className="insight-link">
                    확인하기 <span>→</span>
                  </a>
                </section>

                <div className="section-heading" id="subscriptions">
                  <div>
                    <p className="eyebrow">YOUR SUBSCRIPTIONS</p>
                    <h2>내 구독</h2>
                  </div>
                  <span className="list-count">
                    {subscriptions.length}개 서비스
                  </span>
                </div>
                <section className="subscription-panel">
                  <div className="table-head">
                    <span>서비스</span>
                    <span>결제 금액</span>
                    <span>다음 결제일</span>
                    <span>상태</span>
                    <span />
                  </div>
                  {subscriptions.length === 0 ? (
                    <div className="empty-state">
                      아직 발견된 구독이 없어요.
                    </div>
                  ) : (
                    subscriptions.map((sub) => (
                      <Subscription
                        key={`${sub.merchant}-${sub.amount}`}
                        sub={sub}
                        offline={offlineDemo}
                        onResult={(next, target) => {
                          if (offlineDemo && typeof next === "string") {
                            setResult((current) => ({
                              ...current,
                              subscriptions: current.subscriptions.map(
                                (item) =>
                                  item.merchant === target.merchant &&
                                  item.amount === target.amount
                                    ? {
                                        ...item,
                                        service: next,
                                        confidence: "high",
                                        candidates: [
                                          { service: next, confidence: "high" },
                                        ],
                                        cancel: null,
                                      }
                                    : item,
                              ),
                            }));
                          } else setResult(next);
                        }}
                      />
                    ))
                  )}
                </section>
                <footer className="page-footer">
                  <span className="footer-lock">⌑</span>{" "}
                  {sourceName === "demo_card_2026.csv" ? (
                    <>
                      실제 금융 정보가 아닌 <b>demo_card_2026.csv</b> 가상 결제
                      내역을 분석한 데모예요.
                    </>
                  ) : (
                    <>
                      직접 올린 <b>{sourceName}</b> 결제 내역을 분석했어요.
                    </>
                  )}
                </footer>
              </>
            )
          )}
        </div>
      </main>
    </div>
  );
}

const CONNECT_STEPS = [
  "가상 카드 명세서를 불러오고 있어요",
  "반복 결제와 구독 후보를 살펴보고 있어요",
  "서비스와 다음 결제일을 정리하고 있어요",
];

function Onboarding({ connecting, step, onConnect }) {
  return (
    <main className="onboarding-shell">
      <header className="onboarding-header">
        <a className="onboarding-brand" href="#" aria-label="돈구마">
          <span className="onboarding-brand-mark">
            <img src="/dongguma-logo.svg" alt="" />
          </span>
          돈구마
        </a>
        <span className="onboarding-demo-tag">
          <i /> 체험용 데모
        </span>
      </header>
      <section className="onboarding-content">
        <div className="onboarding-copy">
          <p className="onboarding-eyebrow">HIDDEN SUBSCRIPTIONS, FOUND</p>
          <h1>
            흩어진 결제에서
            <br />
            <em>숨은 구독</em>을 찾아볼까요?
          </h1>
          <p className="onboarding-description">
            가상 결제 내역을 연결하면 돈구마가 반복 결제를 모아
            <br className="desktop-only" /> 구독 서비스와 다음 결제일을
            찾아드려요.
          </p>
          <div className="connect-source-card">
            <div className="source-icon">▤</div>
            <div className="source-copy">
              <b>데모 카드 명세서</b>
              <span>돈구마가 준비한 가상 결제 데이터</span>
            </div>
            <span className="source-badge">시연 데이터</span>
          </div>
          {connecting ? (
            <div className="connect-progress" aria-live="polite">
              <div className="progress-heading">
                <span className="loader" />
                <b>{CONNECT_STEPS[Math.max(0, step - 1)]}</b>
              </div>
              <div className="progress-track">
                <span style={{ width: `${Math.max(8, (step / 3) * 100)}%` }} />
              </div>
              <ol>
                {CONNECT_STEPS.map((label, index) => (
                  <li
                    className={
                      step > index ? "done" : step === index ? "current" : ""
                    }
                    key={label}
                  >
                    <i>{step > index ? "✓" : index + 1}</i>
                    {label}
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            <button
              className="connect-button"
              type="button"
              onClick={onConnect}
            >
              데모 데이터 연동하기 <span>→</span>
            </button>
          )}
          <p className="onboarding-privacy">
            <span>⌑</span> 실제 금융 계정 연결 없이 가상 데이터로만 작동해요.
          </p>
        </div>
        <div className="onboarding-art-wrap">
          <div className="onboarding-art-halo" />
          <img
            className="onboarding-mascot"
            src="/dongguma-mascot-2d.png"
            alt="돈구마가 호미로 땅을 파서 금화와 지폐를 발견한 모습"
          />
          <div className="onboarding-art-caption">
            <span>돈구마의 약속</span>
            <b>
              숨은 구독과 결제일을
              <br />
              한눈에 모아드릴게요.
            </b>
          </div>
        </div>
      </section>
      <footer className="onboarding-footer">
        <span>DON GUMA</span>
        <span>가상 데이터로 경험하는 구독 관리</span>
      </footer>
    </main>
  );
}

function LoadingState() {
  return (
    <div className="loading-state">
      <span className="loader" />
      <b>가상 결제 내역을 분석하고 있어요</b>
      <span>반복 결제와 서비스 후보를 찾는 중이에요.</span>
    </div>
  );
}

function ServiceMark({ name }) {
  const first = (name || "?")
    .replace(/[^A-Za-z가-힣0-9]/g, "")
    .slice(0, 1)
    .toUpperCase();
  const className = /netflix/i.test(name)
    ? "netflix"
    : /apple|icloud/i.test(name)
      ? "apple"
      : /spotify/i.test(name)
        ? "spotify"
        : /youtube/i.test(name)
          ? "youtube"
          : /naver/i.test(name)
            ? "naver"
            : /coupang/i.test(name)
              ? "coupang"
              : "generic";
  return <span className={`service-mark ${className}`}>{first}</span>;
}

const CANCEL_LABELS = {
  web: "해지 안내",
  google_play: "Google Play",
  app_store: "App Store",
};
function Subscription({ sub, onResult, offline }) {
  const confirmed = sub.confidence === "high";
  const changed = sub.price_history?.length > 1;
  const title = sub.service || sub.merchant;
  return (
    <article className="subscription-row">
      <div className="service-cell">
        <ServiceMark name={title} />
        <div className="service-text">
          <b>{title}</b>
          <small>
            {sub.service !== sub.merchant
              ? `명세서 표기 · ${sub.merchant}`
              : sub.plan || "정기 구독"}
          </small>
        </div>
      </div>
      <div className="amount-cell">
        <b>{won(sub.amount)}</b>
        <small>/{CYCLE_LABELS[sub.cycle] || "월"}</small>
        {changed && <span className="price-up">금액 인상</span>}
      </div>
      <div className="date-cell">
        <b>{dateLabel(sub.next_payment_date)}</b>
        <small>예정</small>
      </div>
      <div className="status-cell">
        <span className={`status-badge ${confirmed ? "confirmed" : "review"}`}>
          <i />
          {confirmed ? "확인 완료" : "확인 필요"}
        </span>
        {!confirmed && sub.confidence && (
          <small>{CONFIDENCE_LABELS[sub.confidence]}</small>
        )}
      </div>
      <div className="row-action">
        {confirmed && sub.cancel ? (
          <a
            href={sub.cancel.url}
            target="_blank"
            rel="noreferrer"
            className="cancel-link"
          >
            {CANCEL_LABELS[sub.cancel.via] || "해지 안내"} <span>↗</span>
          </a>
        ) : !confirmed ? (
          <ConfirmService sub={sub} offline={offline} onResult={onResult} />
        ) : (
          <span className="no-action">안내 준비 중</span>
        )}
      </div>
    </article>
  );
}

function ConfirmService({ sub, onResult, offline }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const candidates = useMemo(() => sub.candidates ?? [], [sub.candidates]);
  async function confirm(service) {
    if (offline) {
      onResult(service, sub);
      return;
    }
    setSaving(true);
    setError("");
    try {
      const response = await fetch("/api/merchant-aliases/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          merchant: sub.merchant,
          amount: sub.amount,
          service,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "저장하지 못했어요");
      onResult(data);
    } catch (e) {
      setError(e.message || "저장하지 못했어요");
    } finally {
      setSaving(false);
    }
  }
  if (!candidates.length)
    return <span className="no-action">후보를 찾지 못했어요</span>;
  return (
    <div className="candidate-wrap">
      <span className="candidate-label">실제 서비스 후보</span>
      <div className="candidate-list">
        {candidates.slice(0, 2).map((candidate) => (
          <button
            key={candidate.service}
            className="candidate-button"
            type="button"
            disabled={saving}
            onClick={() => confirm(candidate.service)}
          >
            {candidate.service}
            <span>선택</span>
          </button>
        ))}
      </div>
      {error && <small className="error-text">{error}</small>}
    </div>
  );
}

export default App;
