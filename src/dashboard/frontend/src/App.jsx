import { useEffect, useState, useCallback } from 'react'
import BJCoachPanel from './components/operator/BJCoachPanel'
import PokerAdvisorPanel from './components/operator/PokerAdvisorPanel'

const API_BASE = 'http://localhost:8000'
const APP_STATE_KEY = 'tradehive-operator-shell'

const TABS = [
  { id: 'blackjack', label: 'Blackjack', kicker: 'Coach + Certification' },
  { id: 'poker', label: 'Poker', kicker: 'Live Advisor + Review' },
]

function loadShellState() {
  try {
    const raw = localStorage.getItem(APP_STATE_KEY)
    return raw ? JSON.parse(raw) : { activeTab: 'blackjack' }
  } catch {
    return { activeTab: 'blackjack' }
  }
}

export default function App() {
  const [shellState, setShellState] = useState(loadShellState)
  const [status, setStatus] = useState(null)
  const [statusError, setStatusError] = useState(null)
  const [queueCount, setQueueCount] = useState(0)

  useEffect(() => {
    localStorage.setItem(APP_STATE_KEY, JSON.stringify(shellState))
  }, [shellState])

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/operator/status`)
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail || 'Failed to load operator status')
        setStatus(data)
        setQueueCount(data.poker_review_queue_items || 0)
      } catch (error) {
        setStatusError(error.message)
      }
    }
    fetchStatus()
  }, [])

  const onQueueChange = useCallback((count) => {
    setQueueCount(count)
  }, [])

  const activeTab = shellState.activeTab || 'blackjack'

  return (
    <div className="operator-shell min-h-screen">
      <div className="operator-grid mx-auto max-w-7xl px-6 py-6">

        <header className="operator-hero">
          <div>
            <p className="operator-eyebrow">TradeHive</p>
            <h1 className="operator-title">Advantage Operator</h1>
            <p className="operator-subtitle">
              Card counting coach, poker decision engine, and session review — all deterministic, all local.
            </p>
          </div>

          <div className="operator-status">
            <div className="status-head">
              <span className="status-dot" />
              <span>Systems</span>
            </div>
            {status ? (
              <div className="status-grid">
                <div>
                  <span className="status-label">Profiles</span>
                  <strong>{status.blackjack_profiles}</strong>
                </div>
                <div>
                  <span className="status-label">Queue</span>
                  <strong>{queueCount}</strong>
                </div>
                <div>
                  <span className="status-label">Engine</span>
                  <strong>{status.status}</strong>
                </div>
              </div>
            ) : (
              <p className="status-copy">{statusError || 'Connecting...'}</p>
            )}
          </div>
        </header>

        <nav className="operator-tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              className={`operator-tab ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setShellState((current) => ({ ...current, activeTab: tab.id }))}
            >
              <span className="operator-tab-label">{tab.label}</span>
              <span className="operator-tab-kicker">{tab.kicker}</span>
            </button>
          ))}
        </nav>

        <main>
          {activeTab === 'blackjack' ? (
            <BJCoachPanel apiBase={API_BASE} />
          ) : (
            <PokerAdvisorPanel apiBase={API_BASE} onQueueChange={onQueueChange} />
          )}
        </main>
      </div>
    </div>
  )
}
