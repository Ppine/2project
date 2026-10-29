import { useState } from 'react'

const CYCLE_LABELS = { monthly: '월', yearly: '연' }
const CONFIDENCE_LABELS = { high: '높음', medium: '중간', low: '낮음' }

const won = (n) => `${n.toLocaleString('ko-KR')}원`

function App() {
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

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
      <header>
        <h1>새는 돈 찾기</h1>
        <p>카드 명세서를 올리면 반복 결제를 묶어 구독 목록을 만들어 드려요.</p>
      </header>

      <section className="card">
        <h2>명세서 업로드</h2>
        <form onSubmit={analyze}>
          <input
            type="file"
            aria-label="카드 명세서 파일"
            onChange={(e) => {
              setFile(e.target.files[0] ?? null)
              setError('')
            }}
          />
          <button type="submit" disabled={!file || loading}>
            {loading ? '분석 중…' : '분석하기'}
          </button>
        </form>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>

      {result && <Subscriptions result={result} onResult={setResult} />}
    </main>
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
