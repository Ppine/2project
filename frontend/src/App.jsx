import { useState } from 'react'
import demoCsv from '../../data/demo_card_2026.csv?raw'

const CYCLE_LABELS = { monthly: '월', yearly: '연' }
const CONFIDENCE_LABELS = { high: '높음', medium: '중간', low: '낮음' }

const won = (n) => `${n.toLocaleString('ko-KR')}원`

function App() {
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [dragging, setDragging] = useState(false)

  function pick(next) {
    setFile(next ?? null)
    setError('')
  }

  function useDemo() {
    pick(new File([demoCsv], 'demo_card_2026.csv', { type: 'text/csv' }))
  }

  async function analyze(e) {
    e.preventDefault()
    if (!file) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const body = new FormData()
      body.append('file', file)
      const response = await fetch('/api/statements/', { method: 'POST', body })
      const data = await response.json()
      if (!response.ok) {
        setError(data.detail ?? '분석에 실패했습니다')
      } else {
        setResult(data)
      }
    } catch {
      setError('서버에 연결할 수 없습니다')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main>
      <header className="hero">
        <h1>새는 돈 찾기</h1>
        <p className="lead">
          명세서에 <b>토스페이먼츠</b>, <b>APPLE.COM/BILL</b>로만 찍힌 결제, 정체를 찾아드려요.
        </p>
        <p>카드 명세서를 올리면 반복 결제를 구독으로 묶고, 결제대행사 이름 뒤에 숨은 실제 서비스와 월 구독 합계를 보여줘요.</p>
      </header>

      <section className="card">
        <h2>카드 명세서 올리기</h2>
        <form onSubmit={analyze}>
          <label
            className={`dropzone${dragging ? ' dragging' : ''}${file ? ' has-file' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              pick(e.dataTransfer.files[0])
            }}
          >
            <input
              type="file"
              className="visually-hidden"
              aria-label="카드 명세서 파일"
              onChange={(e) => pick(e.target.files[0])}
            />
            <FileIcon />
            {file ? (
              <>
                <strong>{file.name}</strong>
                <small>다른 파일을 고르려면 다시 클릭하세요</small>
              </>
            ) : (
              <>
                <strong>CSV 파일을 끌어다 놓거나 클릭해서 선택</strong>
                <small>필요한 열: 이용일자 · 가맹점명 · 이용금액</small>
              </>
            )}
          </label>
          <div className="actions">
            <button type="submit" disabled={!file || loading}>
              {loading ? '분석 중…' : '분석하기'}
            </button>
            <button type="button" className="ghost" onClick={useDemo} disabled={loading}>
              데모 명세서로 해보기
            </button>
          </div>
        </form>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <p className="privacy">카드번호는 저장하지 않아요. 날짜 · 가맹점명 · 금액만 분석해요.</p>
      </section>

      {result ? <Subscriptions result={result} onResult={setResult} /> : <Intro />}
    </main>
  )
}

function FileIcon() {
  return (
    <svg className="drop-icon" viewBox="0 0 24 24" width="36" height="36" aria-hidden="true">
      <path
        d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Zm0 0v5h5M12 18v-6m0 0-2.5 2.5M12 12l2.5 2.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

const STEPS = [
  { title: '명세서 올리기', body: '카드사 홈페이지에서 받은 이용내역 CSV를 올려요.' },
  { title: '반복 결제 찾기', body: '같은 곳에 같은 금액이 매달·매년 나간 결제를 구독으로 묶어요.' },
  { title: '정체 밝히기', body: 'PG사·앱마켓 표기를 구독 요금표와 맞춰 실제 서비스와 신뢰도로 바꿔요.' },
]

const EXAMPLES = [
  { merchant: '토스페이먼츠', amount: 14900, service: 'YouTube Premium', confidence: 'high' },
  { merchant: 'APPLE.COM/BILL', amount: 4400, service: 'iCloud+ 200GB', confidence: 'high' },
  { merchant: 'NICE페이', amount: 9900, service: 'Disney+ · Canva · CapCut 중 하나', confidence: 'medium' },
]

function Intro() {
  return (
    <>
      <section className="card">
        <h2>이렇게 찾아드려요</h2>
        <ol className="steps">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <span className="step-no">{i + 1}</span>
              <div>
                <strong>{s.title}</strong>
                <p>{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="card">
        <h2>
          결과 미리보기 <span className="tag">예시</span>
        </h2>
        <ul className="examples">
          {EXAMPLES.map((e) => (
            <li key={e.merchant}>
              <div className="ex-from">
                <small>명세서 표기</small>
                <span>{e.merchant}</span>
              </div>
              <span className="arrow" aria-hidden="true">
                →
              </span>
              <div className="ex-to">
                <small>찾은 서비스</small>
                <span>{e.service}</span>
              </div>
              <div className="ex-side">
                <strong>{won(e.amount)}/월</strong>
                <span className={`badge ${e.confidence}`}>신뢰도 {CONFIDENCE_LABELS[e.confidence]}</span>
              </div>
            </li>
          ))}
        </ul>
        <p className="agent-note">
          Claude 같은 AI 에이전트에서도 MCP로 연결해 &ldquo;나 지금 뭐 구독하고 있어?&rdquo;라고 물어볼 수 있어요.
        </p>
      </section>
    </>
  )
}

const CANCEL_LABELS = {
  web: '해지하기',
  google_play: 'Google Play에서 해지',
  app_store: 'App Store에서 해지',
}

function Subscriptions({ result, onResult }) {
  const { subscriptions, monthly_total: total, transactions } = result
  return (
    <>
      <section className="card total">
        <span>월 구독 합계</span>
        <strong>{won(total)}</strong>
        <small>
          구독 {subscriptions.length}건 · 거래 {transactions}건 분석
        </small>
      </section>

      <section className="card">
        <h2>구독 목록</h2>
        {subscriptions.length === 0 ? (
          <p>반복 결제를 찾지 못했어요.</p>
        ) : (
          <ul className="subs">
            {subscriptions.map((s) => (
              <Subscription key={`${s.merchant}-${s.amount}`} sub={s} onResult={onResult} />
            ))}
          </ul>
        )}
      </section>
    </>
  )
}

function Subscription({ sub, onResult }) {
  const confirmed = sub.confidence === 'high'
  const notes = [
    sub.service !== sub.merchant && `명세서 표기: ${sub.merchant}`,
    sub.price_history.length > 1 && '금액 변경됨',
  ].filter(Boolean)

  return (
    <li className="sub">
      <div className="sub-head">
        <div>
          <div className="sub-name">{sub.service}</div>
          {notes.length > 0 && <small>{notes.join(' · ')}</small>}
        </div>
        <div className="sub-amount">
          {won(sub.amount)}
          <small>/{CYCLE_LABELS[sub.cycle]}</small>
        </div>
      </div>
      <div className="sub-meta">
        <span>다음 결제 {sub.next_payment_date}</span>
        <span className={`badge ${sub.confidence}`}>신뢰도 {CONFIDENCE_LABELS[sub.confidence]}</span>
      </div>
      {confirmed ? (
        sub.cancel && (
          <a className="button secondary" href={sub.cancel.url} target="_blank" rel="noreferrer">
            {CANCEL_LABELS[sub.cancel.via]}
          </a>
        )
      ) : (
        <ConfirmService sub={sub} onResult={onResult} />
      )}
    </li>
  )
}

function ConfirmService({ sub, onResult }) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  if (sub.candidates.length === 0) return <small>어떤 서비스인지 찾지 못했어요.</small>

  async function confirm(service) {
    setSaving(true)
    setError('')
    try {
      const response = await fetch('/api/merchant-aliases/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ merchant: sub.merchant, amount: sub.amount, service }),
      })
      if (!response.ok) throw new Error()
      onResult(await response.json())
    } catch {
      setError('저장하지 못했어요')
      setSaving(false)
    }
  }

  return (
    <div className="confirm">
      <small>어떤 서비스인가요? 확인하면 해지 방법을 알려드려요.</small>
      <div className="chips">
        {sub.candidates.map((c) => (
          <button key={c.service} type="button" className="chip" disabled={saving} onClick={() => confirm(c.service)}>
            {c.service}
          </button>
        ))}
      </div>
      {error && <small className="error">{error}</small>}
    </div>
  )
}

export default App
