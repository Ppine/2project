import { useEffect, useMemo, useRef, useState } from "react";
import demoCsv from "../../data/demo_card_2026.csv?raw";

const DEMO_FILENAME = "demo_card_2026.csv";
const CYCLE_LABELS = { monthly: "월", yearly: "연" };
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
      steps: "iPhone 설정 > 내 이름 > 구독에서 해지",
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
      steps: "Play 스토어 앱 > 프로필 > 결제 및 정기 결제 > 정기 결제에서 해지",
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

// 카드사 홈페이지에서 이용내역을 엑셀/CSV로 받는 경로. 카드사 연동 API가 없어 직접 받아야 한다.
const CARD_ISSUERS = [
  { name: "신한카드", url: "https://www.shinhancard.com" },
  { name: "KB국민카드", url: "https://card.kbcard.com" },
  { name: "삼성카드", url: "https://www.samsungcard.com" },
  { name: "현대카드", url: "https://www.hyundaicard.com" },
  { name: "롯데카드", url: "https://www.lottecard.co.kr" },
  { name: "하나카드", url: "https://www.hanacard.co.kr" },
  { name: "우리카드", url: "https://pc.wooricard.com" },
  { name: "BC카드", url: "https://www.bccard.com" },
];

const NAV_ITEMS = [
  { id: "overview", icon: "▦", label: "대시보드" },
  { id: "insights", icon: "!", label: "알림" },
  { id: "analysis", icon: "◔", label: "소비 분석" },
  { id: "subscriptions", icon: "◷", label: "내 구독" },
  { id: "statements", icon: "▤", label: "가져온 명세서" },
];

const ALERT_META = {
  recharged_after_cancel: { icon: "!", label: "해지 후 결제", tone: "danger" },
  price_change: { icon: "↗", label: "금액 변경", tone: "warn" },
  lapsed: { icon: "?", label: "결제 확인 안 됨", tone: "muted" },
  needs_review: { icon: "✦", label: "출처 확인", tone: "info" },
};

const SHARE_COLORS = [
  "#4a4a4a",
  "#8a5f69",
  "#c98a96",
  "#e2b4bd",
  "#a7737e",
  "#6b5b5b",
  "#d9a3ad",
  "#b9939a",
];
const hostOf = (url) => {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
};

function parseCsvLine(line) {
  return line
    .split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/)
    .map((value) => value.trim().replace(/^"|"$/g, "").replaceAll('""', '"'));
}

const countsTowardTotal = (s) =>
  s.status === "active" || (s.status === "lapsed" && s.missed_cycles < 2);

// 백엔드 analyze()와 같은 모양으로 합계·비중·알림을 채운다 (오프라인 데모용).
function finalizeLocal(base) {
  const counted = base.subscriptions.filter(countsTowardTotal);
  const total = counted.reduce((sum, s) => sum + s.monthly_amount, 0);
  const subscriptions = base.subscriptions.map((s) => ({
    ...s,
    share:
      total && countsTowardTotal(s)
        ? Math.round((s.monthly_amount / total) * 1000) / 10
        : null,
  }));
  const alerts = [];
  for (const s of subscriptions) {
    if (s.status === "cancelled") continue;
    const history = s.price_history;
    if (history.length > 1) {
      const [before, after] = [history.at(-2).amount, history.at(-1).amount];
      alerts.push({
        type: "price_change",
        service: s.service,
        merchant: s.merchant,
        amount: s.amount,
        date: history.at(-1).since,
        message: `${s.service} 요금이 ${Math.abs(after - before).toLocaleString("ko-KR")}원 ${after > before ? "올랐어요" : "내렸어요"} (${won(before)} → ${won(after)})`,
      });
    }
    if (s.confidence !== "high")
      alerts.push({
        type: "needs_review",
        service: s.service,
        merchant: s.merchant,
        amount: s.amount,
        date: s.last_charge_date,
        message: `${s.merchant} ${won(s.amount)} 결제의 실제 서비스를 확인해 주세요`,
      });
  }
  return { ...base, subscriptions, monthly_total: total, alerts };
}

function makeLocalDemo(csv) {
  const [headerLine, ...lines] = csv
    .replace(/^﻿/, "")
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
  const dates = transactions.map((t) => t.date).sort();

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
    const priceHistory = [];
    for (const charge of charges)
      if (priceHistory.at(-1)?.amount !== charge.amount)
        priceHistory.push({ since: charge.date, amount: charge.amount });
    const cancel = definition.cancel
      ? { steps: null, ...definition.cancel, host: hostOf(definition.cancel.url), verified: true }
      : null;
    return [
      {
        service: definition.service,
        merchant: definition.merchant,
        amount: last.amount,
        monthly_amount: last.amount,
        cycle: "monthly",
        next_payment_date: nextDate.toISOString().slice(0, 10),
        first_charge_date: charges[0].date,
        last_charge_date: last.date,
        charge_count: charges.length,
        confidence,
        candidates: (definition.candidates || [definition.service]).map(
          (service) => ({ service, confidence }),
        ),
        evidence: [`매월 ${charges.length}회 결제`],
        price_history: priceHistory,
        plan: definition.plan,
        cancel: confidence === "high" ? cancel : null,
        status: "active",
        status_changed_on: null,
        missed_cycles: 0,
      },
    ];
  }).sort((a, b) => a.next_payment_date.localeCompare(b.next_payment_date));

  return finalizeLocal({
    transactions: transactions.length,
    as_of: dates.at(-1),
    subscriptions,
    statements: [
      {
        id: "local",
        filename: DEMO_FILENAME,
        transactions: transactions.length,
        period_start: dates[0],
        period_end: dates.at(-1),
        uploaded_at: null,
      },
    ],
  });
}

const LOCAL_DEMO = makeLocalDemo(demoCsv);
const dateLabel = (value) => {
  if (!value) return "일정 확인 중";
  const date = new Date(`${value}T00:00:00`);
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
};
const fullDate = (value) => (value ? value.replaceAll("-", ".") : "-");

// Django 가 내려 준 csrftoken 쿠키. 상태를 바꾸는 요청에는 X-CSRFToken 헤더로 함께 보낸다.
const csrfToken = () =>
  document.cookie
    .split("; ")
    .find((cookie) => cookie.startsWith("csrftoken="))
    ?.slice("csrftoken=".length) ?? "";

// 세션이 끝나 401이 오면 App 이 로그인 화면으로 돌아가도록 바꿔 끼운다.
let onAuthLost = () => {};

async function api(path, options = {}) {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = { ...(options.headers ?? {}) };
  if (method !== "GET") headers["X-CSRFToken"] = csrfToken();
  const response = await fetch(path, { credentials: "same-origin", ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) onAuthLost();
  if (!response.ok) {
    const error = new Error(data.detail ?? "요청을 처리하지 못했어요.");
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

const isNetworkError = (e) => e instanceof TypeError;

const jsonPost = (body) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const ACCOUNT_PAGE = { id: "account", label: "계정 관리" };
const PAGES = [...NAV_ITEMS, ACCOUNT_PAGE];
const PAGE_IDS = PAGES.map((item) => item.id);

const pageFromHash = () => {
  const id = window.location.hash.slice(1);
  return PAGE_IDS.includes(id) ? id : PAGE_IDS[0];
};

// 주소의 해시(#subscriptions 등)가 현재 페이지다. 새로고침·뒤로 가기에도 그대로 유지된다.
function usePage() {
  const [page, setPage] = useState(pageFromHash);
  useEffect(() => {
    const sync = () => {
      setPage(pageFromHash());
      window.scrollTo({ top: 0, behavior: "instant" });
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  return page;
}

// 마우스가 왼쪽 가장자리나 사이드바 위에 있는 동안만 열린다. 지나가다 스친 정도로 닫히지 않게 조금 늦게 닫는다.
function useHoverSidebar() {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef(null);
  const show = () => {
    window.clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const hideSoon = () => {
    window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setOpen(false), 200);
  };
  useEffect(() => () => window.clearTimeout(closeTimer.current), []);
  return { open, setOpen, show, hideSoon };
}

function App() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [offlineDemo, setOfflineDemo] = useState(false);
  // checking -> auth(로그인) -> onboarding(데이터 없음) | dashboard
  const [screen, setScreen] = useState("checking");
  const [user, setUser] = useState(null);
  const [connecting, setConnecting] = useState(false);
  const [connectStep, setConnectStep] = useState(0);
  const page = usePage();
  const sidebar = useHoverSidebar();

  // 서버 응답에 statements가 없으면(구독 상태 변경 등) 기존 목록을 유지한다.
  function applyResult(data) {
    setResult((current) => ({
      ...data,
      statements: data.statements ?? current?.statements ?? [],
    }));
  }

  async function postStatement(file) {
    const body = new FormData();
    body.append("file", file);
    return api("/api/statements/", { method: "POST", body });
  }

  async function loadDemo() {
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const data = await postStatement(
        new File([demoCsv], DEMO_FILENAME, { type: "text/csv" }),
      );
      setOfflineDemo(false);
      applyResult(data);
      if (data.statement.added === 0)
        setNotice("데모 명세서는 이미 가져왔어요. 새로 추가된 결제는 없어요.");
    } catch (e) {
      if (isNetworkError(e)) {
        // 백엔드 미실행 상태에서도 프론트 데모를 바로 볼 수 있도록 로컬 예시를 표시합니다.
        setOfflineDemo(true);
        setResult(LOCAL_DEMO);
      } else setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function startOffline() {
    setOfflineDemo(true);
    setResult(LOCAL_DEMO);
    setUser({ username: "오프라인 데모", offline: true });
    setScreen("dashboard");
  }

  // 로그인한 사용자의 데이터를 불러온다. 아직 명세서가 없으면 연동(온보딩) 화면부터 보여 준다.
  async function enterApp() {
    setLoading(true);
    try {
      const data = await api("/api/statements/");
      setOfflineDemo(false);
      if (!data.statements.length) {
        setResult(null);
        setScreen("onboarding");
        return;
      }
      applyResult(data);
      setScreen("dashboard");
    } catch (e) {
      if (isNetworkError(e)) startOffline();
      else if (e.status !== 401) setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function checkSession() {
    try {
      const data = await api("/api/auth/me/");
      setUser(data.user);
      if (data.user) await enterApp();
      else setScreen("auth");
    } catch {
      startOffline();
    }
  }

  async function logout() {
    if (!offlineDemo) await api("/api/auth/logout/", { method: "POST" }).catch(() => {});
    setUser(null);
    setResult(null);
    setOfflineDemo(false);
    setError("");
    setNotice("");
    setScreen("auth");
  }

  async function uploadStatements(files) {
    if (!files?.length) return;
    setLoading(true);
    setError("");
    setNotice("");
    const failed = [];
    let added = 0;
    let last = null;
    for (const file of files) {
      try {
        last = await postStatement(file);
        added += last.statement.added;
      } catch (e) {
        failed.push(
          `${file.name}: ${e instanceof TypeError ? "백엔드에 연결하지 못했어요. 서버가 켜져 있는지 확인해 주세요." : e.message}`,
        );
      }
    }
    if (last) {
      setOfflineDemo(false);
      applyResult(last);
      setNotice(
        added
          ? `명세서 ${files.length - failed.length}개에서 새 결제 ${added}건을 가져왔어요.`
          : "이미 가져온 결제뿐이라 새로 추가된 내역이 없어요.",
      );
    }
    if (failed.length) setError(failed.join(" / "));
    setLoading(false);
  }

  async function deleteStatement(statement) {
    const ok = window.confirm(
      `'${statement.filename}'과 그 결제 ${statement.transactions}건을 지울까요?\n다른 명세서의 결제는 그대로 남아요.`,
    );
    if (!ok) return;
    setError("");
    try {
      const data = await api(`/api/statements/${statement.id}/`, {
        method: "DELETE",
      });
      if (!data.subscriptions)
        setResult({ ...data, subscriptions: [], alerts: [], monthly_total: 0 });
      else applyResult(data);
      setNotice(`'${statement.filename}'을 지웠어요.`);
    } catch (e) {
      setError(e.message);
    }
  }

  async function setSubscriptionStatus(sub, status) {
    if (offlineDemo) {
      setResult((current) =>
        finalizeLocal({
          ...current,
          subscriptions: current.subscriptions.map((item) =>
            item.merchant === sub.merchant && item.amount === sub.amount
              ? {
                  ...item,
                  status,
                  status_changed_on:
                    status === "cancelled"
                      ? new Date().toISOString().slice(0, 10)
                      : null,
                }
              : item,
          ),
        }),
      );
      return;
    }
    try {
      applyResult(
        await api(
          "/api/subscriptions/state/",
          jsonPost({ merchant: sub.merchant, amount: sub.amount, status }),
        ),
      );
    } catch (e) {
      setError(e.message);
    }
  }

  async function resetData() {
    const ok = window.confirm(
      "올린 명세서, 확인한 서비스, 해지 표시를 모두 지울까요?\n지운 데이터는 되돌릴 수 없어요.",
    );
    if (!ok) return;
    // 내 계정의 명세서, 후보 선택 결과, 해지 표시를 모두 지워 처음 상태로 되돌립니다.
    await Promise.all(
      ["/api/statements/", "/api/merchant-aliases/", "/api/subscriptions/state/"].map(
        (path) => api(path, { method: "DELETE" }).catch(() => {}),
      ),
    );
    setResult(null);
    setOfflineDemo(false);
    setError("");
    setNotice("");
    setScreen("onboarding");
    window.location.hash = PAGE_IDS[0];
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
    setScreen("dashboard");
    setConnecting(false);
  }

  useEffect(() => {
    onAuthLost = () => {
      setUser(null);
      setResult(null);
      setScreen("auth");
    };
    checkSession();
    return () => {
      onAuthLost = () => {};
    };
  }, []);

  if (screen === "checking")
    return (
      <main className="onboarding-shell">
        <LoadingState title="로그인 상태를 확인하고 있어요" />
      </main>
    );

  if (screen === "auth")
    return (
      <AuthScreen
        onAuthenticated={(nextUser) => {
          setUser(nextUser);
          enterApp();
        }}
      />
    );

  if (screen === "onboarding")
    return (
      <Onboarding
        connecting={connecting}
        step={connectStep}
        onConnect={connectDemo}
        username={user?.username}
        onLogout={logout}
        error={error}
      />
    );

  const subscriptions = result?.subscriptions ?? [];
  const current = subscriptions.filter((s) => s.status !== "cancelled");
  const cancelled = subscriptions.filter((s) => s.status === "cancelled");
  const alerts = result?.alerts ?? [];
  const needsReview = current.filter((s) => s.confidence !== "high").length;
  const statements = result?.statements ?? [];
  const onlyDemo =
    statements.length > 0 && statements.every((s) => s.filename === DEMO_FILENAME);

  // 대시보드는 모든 섹션을 모아 보여 주고, 각 탭은 자기 섹션만 보여 준다.
  const showOn = (id) => page === PAGE_IDS[0] || page === id;

  const goTo = (id) => {
    window.location.hash = id;
  };
  // 터치 화면은 호버로 닫을 수 없으니 이동하면서 닫는다
  const closeSidebarOnTouch = () => {
    if (window.matchMedia("(hover: none)").matches) sidebar.setOpen(false);
  };

  return (
    <div className={`app-shell${sidebar.open ? " sidebar-open" : ""}`}>
      <div className="sidebar-hover-zone" aria-hidden="true" onMouseEnter={sidebar.show} />
      <aside
        className="sidebar"
        id="app-sidebar"
        onMouseEnter={sidebar.show}
        onMouseLeave={sidebar.hideSoon}
        onFocus={(e) => {
          if (e.target.matches(":focus-visible")) sidebar.show(); // 키보드 Tab 으로 들어올 때
        }}
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget) && !e.currentTarget.matches(":hover"))
            sidebar.hideSoon();
        }}
      >
        <a className="brand" href={`#${PAGE_IDS[0]}`} aria-label="돈구마 대시보드로">
          <span className="brand-mark">
            <img className="brand-logo-image" src="/dongguma-logo.svg" alt="" />
          </span>
          <span>돈구마</span>
        </a>
        <div className="side-label">관리</div>
        <nav className="side-nav" aria-label="메인 메뉴">
          {NAV_ITEMS.map((item) => (
            <a
              key={item.id}
              className={`nav-item${page === item.id ? " active" : ""}`}
              href={`#${item.id}`}
              aria-current={page === item.id ? "page" : undefined}
              onClick={closeSidebarOnTouch}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
              {item.id === "insights" && alerts.length > 0 && (
                <span className="nav-count">{alerts.length}</span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          {(onlyDemo || offlineDemo) && (
            <div className="demo-side-card">
              <span className="demo-dot" />
              데모 데이터
              <p>가상 결제 내역으로 서비스를 둘러보고 있어요.</p>
            </div>
          )}
          <div className="profile-row">
            <a
              className={`profile-link${page === ACCOUNT_PAGE.id ? " active" : ""}`}
              href={`#${ACCOUNT_PAGE.id}`}
              aria-label={`${user?.username} ${ACCOUNT_PAGE.label}`}
              aria-current={page === ACCOUNT_PAGE.id ? "page" : undefined}
              onClick={closeSidebarOnTouch}
            >
              <span className="avatar avatar-mascot">
                <img src="/dongguma-logo.svg" alt="" />
              </span>
              <span className="profile-name">
                <b>{user?.username}</b>
                <small>{offlineDemo ? "서버 연결 없음" : "로그인됨"}</small>
              </span>
            </a>
            <button type="button" className="logout-button" onClick={logout}>
              로그아웃
            </button>
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-button menu-button"
              type="button"
              aria-label={sidebar.open ? "메뉴 닫기" : "메뉴 열기"}
              aria-expanded={sidebar.open}
              aria-controls="app-sidebar"
              onClick={() => sidebar.setOpen((open) => !open)}
              onPointerEnter={(e) => {
                if (e.pointerType === "mouse") sidebar.show(); // 터치는 클릭으로만 연다
              }}
              onPointerLeave={(e) => {
                if (e.pointerType === "mouse") sidebar.hideSoon();
              }}
            >
              <SidebarIcon />
            </button>
            <div className="breadcrumb">
              내 금융 <span>/</span> {PAGES.find((item) => item.id === page).label}
            </div>
          </div>
          <div className="top-actions">
            {!offlineDemo && (
              <button className="replay-onboarding" type="button" onClick={resetData}>
                데이터 초기화
              </button>
            )}
            {(onlyDemo || offlineDemo) && (
              <span className="demo-pill">
                <span className="demo-dot" />
                데모 데이터
              </span>
            )}
            <a className="replay-onboarding top-logout" href={`#${ACCOUNT_PAGE.id}`}>
              계정
            </a>
            <button className="replay-onboarding top-logout" type="button" onClick={logout}>
              로그아웃
            </button>
            <button
              className="icon-button"
              type="button"
              aria-label={`알림 ${alerts.length}건 보기`}
              aria-haspopup="dialog"
              aria-expanded={alertsOpen}
              title="알림 보기"
              onClick={() => setAlertsOpen(true)}
            >
              <BellIcon />
              {alerts.length > 0 && <i />}
            </button>
          </div>
        </header>

        <div className="page-content">
          {page === "overview" && (
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
                  <UploadButton loading={loading} onFiles={uploadStatements} primary />
                  <CardIssuerGuide />
                </div>
              </div>
            </section>
          )}

          {offlineDemo && (
            <div className="error-panel offline-panel" role="status">
              <b>CSV 미리보기</b>
              <span>
                백엔드 연결 전이라 저장소의 {DEMO_FILENAME}를 브라우저에서
                분석해 보여드려요. 명세서 관리는 서버를 켜야 쓸 수 있어요.
              </span>
            </div>
          )}
          {notice && (
            <div className="error-panel offline-panel" role="status">
              <b>알림</b>
              <span>{notice}</span>
              <button type="button" onClick={() => setNotice("")}>
                닫기
              </button>
            </div>
          )}
          {error && (
            <div className="error-panel" role="alert">
              <b>처리하지 못했어요</b>
              <span>{error}</span>
              <button type="button" onClick={() => setError("")}>
                닫기
              </button>
            </div>
          )}

          {page === ACCOUNT_PAGE.id ? (
            <AccountPage
              user={user}
              offline={offlineDemo}
              statements={statements}
              onReset={resetData}
              onLogout={logout}
            />
          ) : loading && !result ? (
            <LoadingState />
          ) : (
            result && (
              <>
                {showOn("insights") && (
                  <AlertsSection alerts={alerts} onReview={() => goTo("subscriptions")} />
                )}

                {page === "overview" && (
                  <section className="summary-grid" aria-label="구독 요약">
                    <article className="summary-card primary-summary">
                      <div className="summary-label">
                        매달 나가는 구독료 <span className="mini-icon">₩</span>
                      </div>
                      <strong>{won(result.monthly_total)}</strong>
                      <div className="summary-foot">
                        해지한 구독을 뺀 월 환산 금액
                      </div>
                      <div className="summary-decoration" aria-hidden="true">
                        ₩
                      </div>
                    </article>
                    <article className="summary-card">
                      <div className="summary-label">
                        구독 중 <span className="mini-icon blue-icon">◷</span>
                      </div>
                      <strong>
                        {current.length}
                        <small>건</small>
                      </strong>
                      <div className="summary-foot">
                        {cancelled.length
                          ? `해지한 구독 ${cancelled.length}건 제외`
                          : "여러 결제처에서 모았어요"}
                      </div>
                    </article>
                    <article className="summary-card coral-summary">
                      <div className="summary-label">
                        확인할 항목 <span className="mini-icon coral-icon">!</span>
                      </div>
                      <strong>
                        {needsReview}
                        <small>건</small>
                      </strong>
                      <div className="summary-foot">실제 서비스를 확인해 주세요</div>
                    </article>
                  </section>
                )}

                {showOn("analysis") && (
                  <ShareAnalysis subscriptions={current} total={result.monthly_total} />
                )}

                {showOn("subscriptions") && (
                  <>
                    <div className="section-heading">
                      <div>
                        <p className="eyebrow">YOUR SUBSCRIPTIONS</p>
                        <h2>내 구독</h2>
                      </div>
                      <span className="list-count">{current.length}개 서비스</span>
                    </div>
                    <section className="subscription-panel">
                      <div className="table-head">
                        <span>서비스</span>
                        <span>결제 금액</span>
                        <span>최근 결제일</span>
                        <span>상태</span>
                        <span>해지</span>
                      </div>
                      {current.length === 0 ? (
                        <div className="empty-state">아직 발견된 구독이 없어요.</div>
                      ) : (
                        current.map((sub) => (
                          <Subscription
                            key={`${sub.merchant}-${sub.amount}`}
                            sub={sub}
                            offline={offlineDemo}
                            onStatus={setSubscriptionStatus}
                            onConfirmed={(next, target) => {
                              if (offlineDemo && typeof next === "string") {
                                setResult((cur) =>
                                  finalizeLocal({
                                    ...cur,
                                    subscriptions: cur.subscriptions.map((item) =>
                                      item.merchant === target.merchant &&
                                      item.amount === target.amount
                                        ? {
                                            ...item,
                                            service: next,
                                            confidence: "high",
                                            candidates: [{ service: next, confidence: "high" }],
                                            cancel: {
                                              via: "app",
                                              url: null,
                                              host: null,
                                              verified: false,
                                              steps: `${next} 앱 > 설정 > 구독·멤버십 관리에서 해지`,
                                            },
                                          }
                                        : item,
                                    ),
                                  }),
                                );
                              } else applyResult(next);
                            }}
                          />
                        ))
                      )}
                    </section>
                    {cancelled.length > 0 && (
                      <details className="cancelled-panel">
                        <summary>
                          해지한 구독 {cancelled.length}개{" "}
                          <small>명세서를 다시 올려도 목록에 돌아오지 않아요</small>
                        </summary>
                        {cancelled.map((sub) => (
                          <div className="cancelled-row" key={`${sub.merchant}-${sub.amount}`}>
                            <ServiceMark name={sub.service} />
                            <div className="service-text">
                              <b>{sub.service}</b>
                              <small>
                                {fullDate(sub.status_changed_on)} 해지 표시 · 마지막 결제{" "}
                                {fullDate(sub.last_charge_date)}
                              </small>
                            </div>
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() => setSubscriptionStatus(sub, "active")}
                            >
                              다시 구독 중이에요
                            </button>
                          </div>
                        ))}
                      </details>
                    )}
                  </>
                )}

                {showOn("statements") && (
                  <StatementsSection
                    statements={statements}
                    offline={offlineDemo}
                    loading={loading}
                    onDelete={deleteStatement}
                    onFiles={uploadStatements}
                    onReloadDemo={loadDemo}
                  />
                )}

                <footer className="page-footer">
                  <span className="footer-lock">⌑</span>{" "}
                  {onlyDemo || offlineDemo ? (
                    <>
                      실제 금융 정보가 아닌 <b>{DEMO_FILENAME}</b> 가상 결제 내역을
                      분석한 데모예요.
                    </>
                  ) : (
                    <>직접 올린 명세서 {statements.length}개의 결제 내역을 분석했어요.</>
                  )}
                </footer>
              </>
            )
          )}
        </div>
      </main>
      <AlertsDrawer
        open={alertsOpen}
        alerts={alerts}
        onClose={() => setAlertsOpen(false)}
        onReview={() => {
          setAlertsOpen(false);
          goTo("subscriptions");
        }}
      />
    </div>
  );
}

function AccountPage({ user, offline, statements, onReset, onLogout }) {
  return (
    <section className="account-page">
      <div className="section-heading compact">
        <div>
          <p className="eyebrow">ACCOUNT</p>
          <h2>{ACCOUNT_PAGE.label}</h2>
        </div>
      </div>

      <article className="account-card account-profile">
        <span className="avatar avatar-mascot account-avatar">
          <img src="/dongguma-logo.svg" alt="" />
        </span>
        <div className="account-profile-text">
          <b>{user?.username}</b>
          <small>{offline ? "서버 연결 없음" : "로그인됨"}</small>
        </div>
        {!offline && (
          <dl className="account-facts">
            <div>
              <dt>가입일</dt>
              <dd>{fullDate(user?.date_joined)}</dd>
            </div>
            <div>
              <dt>가져온 명세서</dt>
              <dd>{statements.length}개</dd>
            </div>
          </dl>
        )}
      </article>

      {offline ? (
        <article className="account-card">
          <h3>서버 연결이 필요해요</h3>
          <p>비밀번호 변경과 데이터 초기화는 백엔드 서버를 켜고 로그인한 뒤 쓸 수 있어요.</p>
        </article>
      ) : (
        <>
          <PasswordForm username={user?.username} />
          <article className="account-card">
            <h3>데이터 초기화</h3>
            <p>이 계정의 명세서, 확인한 서비스, 해지 표시를 모두 지워요. 지운 데이터는 되돌릴 수 없어요.</p>
            <button type="button" className="ghost-button danger" onClick={onReset}>
              데이터 초기화
            </button>
          </article>
        </>
      )}

      <article className="account-card">
        <h3>로그아웃</h3>
        <p>{offline ? "데모 화면을 닫고 로그인 화면으로 돌아가요." : "이 브라우저에서 로그아웃해요."}</p>
        <button type="button" className="ghost-button" onClick={onLogout}>
          로그아웃
        </button>
      </article>
    </section>
  );
}

function PasswordForm({ username }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fields, setFields] = useState({});
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setDone(false);
    setError("");
    setFields({});
    if (next !== confirm) {
      setFields({ confirm: ["새 비밀번호가 서로 달라요."] });
      return;
    }
    setBusy(true);
    try {
      await api("/api/auth/password/", {
        ...jsonPost({ current_password: current, new_password: next }),
      });
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(true);
    } catch (err) {
      if (err.data?.fields) setFields(err.data.fields);
      else setError(isNetworkError(err) ? "서버에 연결하지 못했어요." : err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="account-card auth-card account-password" onSubmit={submit} noValidate>
      <h3>비밀번호 변경</h3>
      <input type="text" name="username" autoComplete="username" value={username ?? ""} readOnly hidden />
      <label>
        현재 비밀번호
        <input
          type="password"
          name="current-password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          aria-invalid={Boolean(fields.current_password)}
        />
        {fields.current_password && <small className="field-error">{fields.current_password.join(" ")}</small>}
      </label>
      <label>
        새 비밀번호
        <input
          type="password"
          name="new-password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          aria-invalid={Boolean(fields.new_password)}
        />
        {fields.new_password ? (
          <small className="field-error">{fields.new_password.join(" ")}</small>
        ) : (
          <small>8자 이상, 흔하거나 숫자로만 된 비밀번호는 쓸 수 없어요.</small>
        )}
      </label>
      <label>
        새 비밀번호 확인
        <input
          type="password"
          name="confirm-password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={Boolean(fields.confirm)}
        />
        {fields.confirm && <small className="field-error">{fields.confirm.join(" ")}</small>}
      </label>
      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
      {done && (
        <p className="account-success" role="status">
          비밀번호를 바꿨어요. 다른 기기에서는 다시 로그인해야 해요.
        </p>
      )}
      <button type="submit" className="ghost-button" disabled={busy || !current || !next || !confirm}>
        {busy ? "바꾸는 중…" : "비밀번호 변경"}
      </button>
    </form>
  );
}

function SidebarIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3.5" y="5" width="17" height="14" rx="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M9.5 5v14" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16Z M10 20a2 2 0 0 0 4 0"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function UploadButton({ loading, onFiles, primary }) {
  return (
    <label
      className={`refresh-button upload-button${primary ? " primary-button" : ""}${loading ? " disabled" : ""}`}
    >
      <input
        type="file"
        accept=".csv,.png,.jpg,.jpeg,.webp,.heic"
        multiple
        disabled={loading}
        onChange={(e) => {
          onFiles([...(e.target.files ?? [])]);
          e.target.value = "";
        }}
      />
      <span className={loading ? "spin" : ""}>{loading ? "↻" : "⇪"}</span> 내 명세서
      올리기
    </label>
  );
}

function CardIssuerGuide() {
  return (
    <details className="issuer-guide">
      <summary className="refresh-button">
        <span>▤</span> 명세서 받으러 가기
      </summary>
      <div className="issuer-menu">
        <p>
          카드사 홈페이지 로그인 → <b>이용내역 조회</b> → 기간을 <b>최근 12개월</b>로
          정하고 <b>엑셀/CSV 다운로드</b>
        </p>
        <ul>
          {CARD_ISSUERS.map((issuer) => (
            <li key={issuer.name}>
              <a href={issuer.url} target="_blank" rel="noreferrer">
                {issuer.name}
                <small>{hostOf(issuer.url)}</small>
                <span>↗</span>
              </a>
            </li>
          ))}
        </ul>
        <small className="issuer-note">
          여러 달 치 파일을 한 번에 골라 올릴 수 있어요. 겹치는 결제는 자동으로
          한 번만 저장돼요.
        </small>
      </div>
    </details>
  );
}

function AlertsSection({ alerts, onReview }) {
  return (
    <section className="alerts-section" aria-label="알림">
      <div className="section-heading compact">
        <div>
          <p className="eyebrow">ALERTS</p>
          <h2>새로 확인할 알림</h2>
        </div>
        <span className="list-count">{alerts.length}건</span>
      </div>
      <AlertList alerts={alerts} onReview={onReview} />
    </section>
  );
}

function AlertList({ alerts, onReview }) {
  if (alerts.length === 0)
    return (
      <div className="alert-card calm">
        <span className="alert-icon">✓</span>
        <div>
          <b>새로 알릴 내용이 없어요</b>
          <small>금액 변경이나 놓친 결제가 생기면 여기에 먼저 알려드릴게요.</small>
        </div>
      </div>
    );
  return (
    <ul className="alert-list">
      {alerts.map((alert, index) => {
        const meta = ALERT_META[alert.type] ?? ALERT_META.needs_review;
        return (
          <li className={`alert-card ${meta.tone}`} key={`${alert.type}-${alert.merchant}-${alert.amount}-${index}`}>
            <span className="alert-icon">{meta.icon}</span>
            <div>
              <span className="alert-kicker">
                {meta.label} · {fullDate(alert.date)}
              </span>
              <b>{alert.message}</b>
            </div>
            {alert.type === "needs_review" && (
              <button type="button" className="ghost-button" onClick={onReview}>
                확인하기 →
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// 네이티브 <dialog> 라서 포커스 가두기·Esc 닫기·닫은 뒤 포커스 복귀를 브라우저가 처리한다.
function AlertsDrawer({ open, alerts, onClose, onReview }) {
  const dialogRef = useRef(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={dialogRef}
      className="alerts-drawer"
      aria-labelledby="alerts-drawer-title"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose(); // 바깥 어두운 영역 클릭
      }}
    >
      <div className="alerts-drawer-panel">
        <header className="alerts-drawer-head">
          <div>
            <p className="eyebrow">ALERTS</p>
            <h2 id="alerts-drawer-title">알림</h2>
          </div>
          <span className="list-count">{alerts.length}건</span>
          <button type="button" className="alerts-drawer-close" aria-label="알림 닫기" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="alerts-drawer-body">
          <AlertList alerts={alerts} onReview={onReview} />
        </div>
      </div>
    </dialog>
  );
}

// 색이 8개뿐이라 그보다 많으면 작은 항목을 "기타"로 묶는다.
function shareItems(subscriptions) {
  const items = subscriptions
    .filter((s) => s.share != null)
    .sort((a, b) => b.share - a.share)
    .map((s) => ({
      key: `${s.merchant}-${s.amount}`,
      name: s.service,
      share: s.share,
      amount: s.monthly_amount,
    }));
  if (items.length <= SHARE_COLORS.length) return items;
  const rest = items.slice(SHARE_COLORS.length - 1);
  const sum = (field) => rest.reduce((total, item) => total + item[field], 0);
  return [
    ...items.slice(0, SHARE_COLORS.length - 1),
    { key: "others", name: `기타 ${rest.length}개`, share: Math.round(sum("share") * 10) / 10, amount: sum("amount") },
  ];
}

const PIE_SIZE = 220;
const PIE_RADIUS = PIE_SIZE / 2 - 2;

function pieSlicePath(from, to) {
  const center = PIE_SIZE / 2;
  const point = (ratio) => {
    const angle = 2 * Math.PI * ratio - Math.PI / 2; // 12시 방향에서 시계 방향으로
    return `${center + PIE_RADIUS * Math.cos(angle)} ${center + PIE_RADIUS * Math.sin(angle)}`;
  };
  const large = to - from > 0.5 ? 1 : 0;
  return `M ${center} ${center} L ${point(from)} A ${PIE_RADIUS} ${PIE_RADIUS} 0 ${large} 1 ${point(to)} Z`;
}

function ShareAnalysis({ subscriptions, total }) {
  const [active, setActive] = useState(null);
  const [tip, setTip] = useState(null);
  const items = shareItems(subscriptions);
  if (!items.length) return null;
  const shareSum = items.reduce((sum, item) => sum + item.share, 0);
  const slices = items.reduce((list, item, i) => {
    const from = list.at(-1)?.to ?? 0;
    return [...list, { ...item, from, to: from + item.share / shareSum, color: SHARE_COLORS[i] }];
  }, []);
  const dim = (key) => (active && active !== key ? " dimmed" : "");
  const activeItem = slices.find((slice) => slice.key === active);
  return (
    <section className="analysis-panel">
      <div className="analysis-head">
        <div>
          <p className="eyebrow">SUBSCRIPTION ANALYSIS</p>
          <h2>구독 데이터 분석</h2>
        </div>
        <small>월 환산 구독료 합계 {won(total)} 대비</small>
      </div>
      <div className="share-chart">
        <div className="share-pie" onPointerLeave={() => setActive(null)}>
          <svg
            viewBox={`0 0 ${PIE_SIZE} ${PIE_SIZE}`}
            role="img"
            aria-label={`서비스별 구독료 비중: ${slices.map((s) => `${s.name} ${s.share}%`).join(", ")}`}
            onPointerMove={(e) => {
              const box = e.currentTarget.getBoundingClientRect();
              setTip({ x: e.clientX - box.left, y: e.clientY - box.top });
            }}
          >
            {slices.length === 1 ? (
              <circle
                cx={PIE_SIZE / 2}
                cy={PIE_SIZE / 2}
                r={PIE_RADIUS}
                fill={slices[0].color}
                onPointerEnter={() => setActive(slices[0].key)}
              />
            ) : (
              slices.map((slice) => (
                <path
                  key={slice.key}
                  className={`share-slice${dim(slice.key)}`}
                  d={pieSlicePath(slice.from, slice.to)}
                  fill={slice.color}
                  onPointerEnter={() => setActive(slice.key)}
                />
              ))
            )}
          </svg>
          {activeItem && tip && (
            <div className="share-tip" style={{ left: tip.x, top: tip.y }}>
              <b>{activeItem.name}</b>
              <span>
                {activeItem.share}% · {won(activeItem.amount)}
              </span>
            </div>
          )}
        </div>
        <ol className="share-legend">
          {slices.map((slice) => (
            <li
              key={slice.key}
              className={dim(slice.key).trim()}
              onPointerEnter={() => {
                setTip(null);
                setActive(slice.key);
              }}
              onPointerLeave={() => setActive(null)}
            >
              <i style={{ background: slice.color }} />
              <span title={slice.name}>{slice.name}</span>
              <b>{slice.share}%</b>
              <small>{won(slice.amount)}</small>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function monthsBetween(start, end) {
  const [y1, m1] = start.split("-").map(Number);
  const [y2, m2] = end.split("-").map(Number);
  return (y2 - y1) * 12 + (m2 - m1) + 1;
}

function StatementsSection({ statements, offline, loading, onDelete, onFiles, onReloadDemo }) {
  const starts = statements.map((s) => s.period_start).filter(Boolean).sort();
  const ends = statements.map((s) => s.period_end).filter(Boolean).sort();
  const months = starts.length ? monthsBetween(starts[0], ends.at(-1)) : 0;
  return (
    <section className="statements-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">STATEMENTS</p>
          <h2>가져온 명세서</h2>
        </div>
        {months > 0 && (
          <span className="list-count">
            {fullDate(starts[0]).slice(0, 7)} ~ {fullDate(ends.at(-1)).slice(0, 7)} · {months}개월치
          </span>
        )}
      </div>
      {months > 0 && months < 12 && (
        <p className="coverage-tip">
          정기 결제 주기를 정확히 판단하려면 <b>12개월치</b>를 권장해요. 지금은{" "}
          {months}개월치예요. 연간 구독은 1년 이상 이력이 있어야 찾을 수 있어요.
        </p>
      )}
      <div className="statement-panel">
        {statements.length === 0 ? (
          <div className="empty-state">아직 가져온 명세서가 없어요.</div>
        ) : (
          statements.map((s) => (
            <div className="statement-row" key={s.id}>
              <span className="statement-icon">▤</span>
              <div className="service-text">
                <b>{s.filename}</b>
                <small>
                  {fullDate(s.period_start)} ~ {fullDate(s.period_end)} · 결제{" "}
                  {s.transactions}건
                  {s.uploaded_at &&
                    ` · ${new Date(s.uploaded_at).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" })} 업로드`}
                </small>
              </div>
              <button
                type="button"
                className="ghost-button danger"
                disabled={offline}
                title={offline ? "서버를 켜야 지울 수 있어요" : undefined}
                onClick={() => onDelete(s)}
              >
                삭제
              </button>
            </div>
          ))
        )}
      </div>
      <div className="statement-actions">
        <UploadButton loading={loading} onFiles={onFiles} />
        <button className="refresh-button" type="button" onClick={onReloadDemo} disabled={loading}>
          <span className={loading ? "spin" : ""}>↻</span> 데모 명세서 다시 불러오기
        </button>
      </div>
    </section>
  );
}

const CONNECT_STEPS = [
  "가상 카드 명세서를 불러오고 있어요",
  "반복 결제와 구독 후보를 살펴보고 있어요",
  "서비스와 다음 결제일을 정리하고 있어요",
];

function Onboarding({ connecting, step, onConnect, username, onLogout, error }) {
  return (
    <main className="onboarding-shell">
      <BrandHeader>
        <span className="onboarding-user">
          <b>{username}</b>
          <button type="button" className="replay-onboarding" onClick={onLogout}>
            로그아웃
          </button>
        </span>
      </BrandHeader>
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
          {error && (
            <p className="auth-error" role="alert">
              {error}
            </p>
          )}
          <p className="onboarding-privacy">
            <span>⌑</span> 실제 금융 계정 연결 없이 가상 데이터로 먼저 둘러볼 수 있어요.
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

function LoadingState({ title }) {
  return (
    <div className="loading-state">
      <span className="loader" />
      <b>{title ?? "결제 내역을 분석하고 있어요"}</b>
      {!title && <span>반복 결제와 서비스 후보를 찾는 중이에요.</span>}
    </div>
  );
}

function BrandHeader({ children }) {
  return (
    <header className="onboarding-header">
      <span className="onboarding-brand">
        <span className="onboarding-brand-mark">
          <img src="/dongguma-logo.svg" alt="" />
        </span>
        돈구마
      </span>
      {children}
    </header>
  );
}

function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [fields, setFields] = useState({});
  const [busy, setBusy] = useState(false);
  const signup = mode === "signup";

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFields({});
    try {
      const data = await api(`/api/auth/${mode}/`, jsonPost({ username, password }));
      setPassword("");
      onAuthenticated(data.user);
    } catch (e) {
      setError(isNetworkError(e) ? "서버에 연결하지 못했어요. 백엔드가 켜져 있는지 확인해 주세요." : e.message);
      setFields(e.data?.fields ?? {});
    } finally {
      setBusy(false);
    }
  }

  function switchMode() {
    setMode(signup ? "login" : "signup");
    setError("");
    setFields({});
  }

  return (
    <main className="onboarding-shell">
      <BrandHeader />
      <section className="onboarding-content">
        <div className="onboarding-copy">
          <p className="onboarding-eyebrow">{signup ? "CREATE ACCOUNT" : "WELCOME BACK"}</p>
          <h1>
            {signup ? (
              <>
                내 구독을
                <br />
                <em>나만 보게</em> 시작해요
              </>
            ) : (
              <>
                다시 오셨네요,
                <br />
                <em>숨은 돈</em> 찾으러 가요
              </>
            )}
          </h1>
          <p className="onboarding-description">
            명세서와 구독 정보는 계정마다 따로 저장되고, 로그인한 본인만 볼 수 있어요.
          </p>
          <form className="auth-card" onSubmit={submit} noValidate>
            <label>
              아이디
              <input
                name="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={3}
                maxLength={30}
                aria-invalid={Boolean(fields.username)}
              />
              {fields.username && <small className="field-error">{fields.username.join(" ")}</small>}
              {signup && !fields.username && (
                <small>3~30자, 영문·숫자와 @ . + - _ 만 쓸 수 있어요.</small>
              )}
            </label>
            <label>
              비밀번호
              <input
                name="password"
                type="password"
                autoComplete={signup ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                aria-invalid={Boolean(fields.password)}
              />
              {fields.password && <small className="field-error">{fields.password.join(" ")}</small>}
              {signup && !fields.password && (
                <small>8자 이상, 흔하거나 숫자로만 된 비밀번호는 쓸 수 없어요.</small>
              )}
            </label>
            {error && !Object.keys(fields).length && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
            <button className="connect-button" type="submit" disabled={busy || !username || !password}>
              {busy ? "확인하는 중…" : signup ? "가입하고 시작하기" : "로그인"} <span>→</span>
            </button>
          </form>
          <p className="auth-switch">
            {signup ? "이미 계정이 있나요?" : "처음이신가요?"}{" "}
            <button type="button" onClick={switchMode}>
              {signup ? "로그인" : "회원가입"}
            </button>
          </p>
        </div>
        <div className="onboarding-art-wrap">
          <div className="onboarding-art-halo" />
          <img
            className="onboarding-mascot"
            src="/dongguma-mascot-2d.png"
            alt="돈구마가 호미로 땅을 파서 금화와 지폐를 발견한 모습"
          />
        </div>
      </section>
    </main>
  );
}

// 서비스명(또는 확인 전 가맹점 표기) -> public/logos/<파일>.png
// 로고는 각 서비스 공식 사이트의 아이콘을 받아 저장해 두었다. 화면을 열 때 외부 서버로 요청하지 않는다.
// 위에서부터 먼저 맞는 항목을 쓰므로 구체적인 이름(YouTube Music)을 일반적인 이름(YouTube)보다 위에 둔다.
const SERVICE_LOGOS = [
  [/youtube\s*music/i, "youtube-music"],
  [/youtube/i, "youtube"],
  [/netflix/i, "netflix"],
  [/spotify/i, "spotify"],
  [/icloud/i, "icloud"],
  [/apple\s*music/i, "apple-music"],
  [/apple\s*tv/i, "apple-tv"],
  [/naver|네이버/i, "naver"],
  [/coupang|쿠팡/i, "coupang"],
  [/disney/i, "disney-plus"],
  [/canva/i, "canva"],
  [/capcut/i, "capcut"],
  [/chatgpt|openai/i, "chatgpt"],
  [/claude|anthropic/i, "claude"],
  [/adobe/i, "adobe"],
  [/microsoft|office/i, "microsoft-365"],
  [/duolingo/i, "duolingo"],
  [/perplexity/i, "perplexity"],
  [/kakao|카카오/i, "kakao"],
  [/tving|티빙/i, "tving"],
  [/wavve|웨이브/i, "wavve"],
  [/watcha|왓챠/i, "watcha"],
  [/gemini|google\s*ai/i, "gemini"],
  [/grok/i, "grok"],
  [/baemin|배민|배달의민족/i, "baemin"],
  [/class101/i, "class101"],
  [/ebs/i, "ebs"],
  [/speak/i, "speak"],
  [/millie|밀리/i, "millie"],
  // 서비스를 확인하기 전 앱마켓 묶음 표기
  [/^apple\.com\/bill/i, "app-store"],
  [/^google/i, "google-play"],
];

function ServiceMark({ name }) {
  const [failed, setFailed] = useState(null);
  const logo = SERVICE_LOGOS.find(([pattern]) => pattern.test(name || ""))?.[1];
  if (logo && failed !== logo)
    return (
      <span className="service-mark has-logo">
        <img src={`/logos/${logo}.png`} alt="" onError={() => setFailed(logo)} />
      </span>
    );
  // 로고가 없는 서비스(PG사 표기 등)는 첫 글자로 표시한다.
  const first = (name || "?")
    .replace(/[^A-Za-z가-힣0-9]/g, "")
    .slice(0, 1)
    .toUpperCase();
  return <span className="service-mark">{first}</span>;
}

const CANCEL_PLACE = {
  web: "서비스 웹사이트",
  app_store: "App Store 구독 관리",
  google_play: "Google Play 정기 결제",
  app: "서비스 앱",
};

function CancelAction({ cancel }) {
  if (!cancel) return <span className="no-action">해지 경로 준비 중</span>;
  if (!cancel.url)
    return (
      <span className="cancel-app" title={cancel.steps}>
        앱에서 해지
        <small>웹 해지 불가 · 상세에서 방법 보기</small>
      </span>
    );
  return (
    <span className="cancel-wrap">
      <a href={cancel.url} target="_blank" rel="noreferrer" className="cancel-link">
        해지하러 가기 <span>↗</span>
      </a>
      <small className="cancel-host">
        {cancel.host}
        {cancel.verified && <em> · 공식 경로</em>}
      </small>
    </span>
  );
}

function Subscription({ sub, onConfirmed, onStatus, offline }) {
  const [open, setOpen] = useState(false);
  const confirmed = sub.confidence === "high";
  const title = sub.service || sub.merchant;
  const lapsed = sub.status === "lapsed";
  return (
    <article className={`subscription-item${open ? " open" : ""}`}>
      <div className="subscription-row">
        <button
          type="button"
          className="service-cell service-toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <ServiceMark name={title} />
          <span className="service-text">
            <b>{title}</b>
            <small>
              {sub.service !== sub.merchant
                ? `명세서 표기 · ${sub.merchant}`
                : sub.plan || "정기 구독"}
            </small>
          </span>
          <span className="chevron" aria-hidden="true">
            ⌄
          </span>
        </button>
        <div className="amount-cell">
          <b>{won(sub.amount)}</b>
          <small>/{CYCLE_LABELS[sub.cycle] || "월"}</small>
          {sub.share != null && <span className="share-chip">구독료의 {sub.share}%</span>}
        </div>
        <div className="date-cell">
          <b>{dateLabel(sub.last_charge_date)}</b>
          <small className={lapsed ? "overdue" : ""}>
            {lapsed
              ? `예상일 ${dateLabel(sub.next_payment_date)} 지남`
              : `다음 결제 예상 · ${dateLabel(sub.next_payment_date)}`}
          </small>
        </div>
        <div className="status-cell">
          <span className={`status-badge ${confirmed ? "confirmed" : "review"}`}>
            <i />
            {confirmed ? "서비스 확인됨" : "출처 확인 필요"}
          </span>
          {lapsed && (
            <span className="status-badge lapsed">
              <i />
              {sub.missed_cycles > 1 ? "결제 끊김" : "결제 확인 안 됨"}
            </span>
          )}
          {sub.recharged_after_cancel && (
            <span className="status-badge danger">
              <i />
              해지 후 결제됨
            </span>
          )}
        </div>
        <div className="row-action">
          {confirmed ? (
            <CancelAction cancel={sub.cancel} />
          ) : (
            <ConfirmService sub={sub} offline={offline} onResult={onConfirmed} />
          )}
        </div>
      </div>
      {open && <SubscriptionDetail sub={sub} onStatus={onStatus} />}
    </article>
  );
}

function SubscriptionDetail({ sub, onStatus }) {
  const history = sub.price_history ?? [];
  return (
    <div className="subscription-detail">
      <dl className="detail-grid">
        <div>
          <dt>첫 결제</dt>
          <dd>{fullDate(sub.first_charge_date)}</dd>
        </div>
        <div>
          <dt>최근 결제</dt>
          <dd>{fullDate(sub.last_charge_date)}</dd>
        </div>
        <div>
          <dt>결제 횟수</dt>
          <dd>{sub.charge_count}회</dd>
        </div>
        <div>
          <dt>다음 결제 (예상)</dt>
          <dd>{fullDate(sub.next_payment_date)}</dd>
        </div>
      </dl>
      <div className="detail-columns">
        <div>
          <h3>금액 이력</h3>
          <ol className="price-history">
            {history.map((h) => (
              <li key={`${h.since}-${h.amount}`}>
                <span>{fullDate(h.since)}부터</span>
                <b>{won(h.amount)}</b>
              </li>
            ))}
          </ol>
          {sub.share != null && (
            <p className="detail-note">
              월 환산 구독료 합계 대비 <b>{sub.share}%</b>를 차지해요.
            </p>
          )}
        </div>
        <div>
          <h3>해지 방법</h3>
          {sub.cancel ? (
            <>
              <p className="detail-note">
                {CANCEL_PLACE[sub.cancel.via] ?? "서비스"}에서 해지해요.
                {sub.cancel.host && (
                  <>
                    {" "}
                    이동할 주소: <b>{sub.cancel.host}</b>
                    {sub.cancel.verified &&
                      " (돈구마가 확인한 공식 해지 경로예요)"}
                  </>
                )}
              </p>
              {sub.cancel.steps && <p className="detail-steps">{sub.cancel.steps}</p>}
            </>
          ) : (
            <p className="detail-note">
              실제 서비스를 확인하면 해지 경로를 알려드릴게요.
            </p>
          )}
          {sub.evidence?.length > 0 && (
            <>
              <h3>판단 근거</h3>
              <ul className="evidence-list">
                {sub.evidence.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
      <div className="detail-actions">
        <span>
          이미 해지했다면 표시해 두세요. 다음 명세서를 올리기 전에도 목록과 합계에서
          빠지고, 나중에 다시 결제되면 알려드려요.
        </span>
        <button type="button" className="ghost-button" onClick={() => onStatus(sub, "cancelled")}>
          해지했어요
        </button>
      </div>
    </div>
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
      onResult(
        await api(
          "/api/merchant-aliases/",
          jsonPost({ merchant: sub.merchant, amount: sub.amount, service }),
        ),
      );
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
