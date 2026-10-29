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

      {result && <Subscriptions result={result} />}
    </main>
  )
}

function Subscriptions({ result }) {
  const { subscriptions, monthly_total: total, statement } = result
  return (
    <>
      <section className="card total">
        <span>월 구독 합계</span>
        <strong>{won(total)}</strong>
        <small>
          구독 {subscriptions.length}건 · 거래 {statement.transactions}건 분석
        </small>
      </section>

      <section className="card">
        <h2>구독 목록</h2>
        {subscriptions.length === 0 ? (
          <p>반복 결제를 찾지 못했어요.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>서비스</th>
                  <th className="num">금액</th>
                  <th>주기</th>
                  <th>다음 결제일</th>
                  <th>신뢰도</th>
                </tr>
              </thead>
              <tbody>
                {subscriptions.map((s) => (
                  <tr key={`${s.merchant}-${s.amount}`}>
                    <td>
                      <div>{s.service}</div>
                      <small>
                        {s.service !== s.merchant && `명세서 표기: ${s.merchant}`}
                        {s.confidence !== 'high' && s.candidates.length > 0 &&
                          ` · 후보: ${s.candidates.map((c) => c.service).join(', ')}`}
                        {s.price_history.length > 1 && ' · 금액 변경됨'}
                      </small>
                    </td>
                    <td className="num">{won(s.amount)}</td>
                    <td>{CYCLE_LABELS[s.cycle]}</td>
                    <td>{s.next_payment_date}</td>
                    <td>
                      <span className={`badge ${s.confidence}`}>{CONFIDENCE_LABELS[s.confidence]}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}

export default App
