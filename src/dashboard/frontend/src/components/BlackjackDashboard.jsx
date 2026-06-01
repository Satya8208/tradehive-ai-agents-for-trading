import { useState, useRef, useCallback, useEffect } from 'react'

const API_BASE = 'http://localhost:8002'

// Card suits for decorative elements
const SUITS = ['♠', '♥', '♦', '♣']

// Mode configurations with casino colors
const MODES = {
  card_counter: {
    label: 'Card Counter',
    icon: '🎯',
    color: '#06b6d4',
    pattern: 'THE ODDS FLIP',
    description: 'Mathematical precision'
  },
  high_roller: {
    label: 'High Roller',
    icon: '💎',
    color: '#eab308',
    pattern: 'THE BET REVEAL',
    description: 'Calculated boldness'
  },
  table_reader: {
    label: 'Table Reader',
    icon: '👁',
    color: '#a855f7',
    pattern: 'THE TABLE READ',
    description: 'Psychological insight'
  },
  bankroll_manager: {
    label: 'Bankroll',
    icon: '🛡',
    color: '#10b981',
    pattern: 'POSITION SIZE',
    description: 'Strategic survival'
  },
  the_dealer: {
    label: 'The Dealer',
    icon: '🃏',
    color: '#94a3b8',
    pattern: 'DEALER\'S VIEW',
    description: 'Cool detachment'
  },
  shark: {
    label: 'Shark',
    icon: '🦈',
    color: '#ef4444',
    pattern: 'EV CALCULATION',
    description: 'Aggressive precision'
  },
}

// Copy hook
function useCopy() {
  const [copied, setCopied] = useState(null)
  const copy = async (text, id) => {
    await navigator.clipboard.writeText(text)
    setCopied(id)
    setTimeout(() => setCopied(null), 2000)
  }
  return { copied, copy }
}

// Floating card suits background
function FloatingSuits() {
  return (
    <div className="fixed inset-0 overflow-hidden pointer-events-none opacity-[0.03]">
      {[...Array(20)].map((_, i) => (
        <span
          key={i}
          className="absolute text-6xl font-bold"
          style={{
            left: `${Math.random() * 100}%`,
            top: `${Math.random() * 100}%`,
            color: i % 4 < 2 ? '#ef4444' : '#fafafa',
            transform: `rotate(${Math.random() * 360}deg)`,
          }}
        >
          {SUITS[i % 4]}
        </span>
      ))}
    </div>
  )
}

// Casino chip decoration
function ChipDeco({ size = 'md', color = '#f59e0b' }) {
  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8'
  }
  return (
    <div
      className={`${sizeClasses[size]} rounded-full border-2 border-dashed flex items-center justify-center`}
      style={{ borderColor: color, backgroundColor: `${color}20` }}
    >
      <div className="w-1/2 h-1/2 rounded-full" style={{ backgroundColor: color }} />
    </div>
  )
}

// Analysis Panel - Shows the betting wisdom breakdown
function AnalysisPanel({ analysis }) {
  if (!analysis) return null

  const modeConfig = MODES[analysis.recommended_mode] || MODES.card_counter

  const engagementColors = {
    low: '#94a3b8',
    medium: '#eab308',
    high: '#10b981',
    viral: '#ef4444'
  }

  return (
    <div className="bj-analysis-panel mb-6 fade-in">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg bg-amber-500/20 flex items-center justify-center">
          <span className="text-amber-400 text-lg">♠</span>
        </div>
        <div>
          <h3 className="font-semibold text-amber-400" style={{ fontFamily: "'Playfair Display', serif" }}>
            Table Read
          </h3>
          <p className="text-xs text-gray-500">Analysis complete</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div className="bj-stat-box">
          <span className="text-gray-500 text-xs uppercase tracking-wider">The Bet</span>
          <p className="text-white mt-1 font-medium">{analysis.the_bet}</p>
        </div>

        <div className="bj-stat-box">
          <span className="text-gray-500 text-xs uppercase tracking-wider">Best Play</span>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-lg">{modeConfig.icon}</span>
            <span
              className="font-semibold"
              style={{ color: modeConfig.color }}
            >
              {modeConfig.label}
            </span>
          </div>
        </div>

        <div className="bj-stat-box">
          <span className="text-gray-500 text-xs uppercase tracking-wider">Angle</span>
          <p className="text-white mt-1">{analysis.angle}</p>
        </div>

        <div className="bj-stat-box">
          <span className="text-gray-500 text-xs uppercase tracking-wider">Engagement EV</span>
          <div className="flex items-center gap-2 mt-1">
            <span
              className="px-2 py-0.5 rounded text-xs font-bold uppercase"
              style={{
                backgroundColor: `${engagementColors[analysis.engagement_potential?.toLowerCase()]}20`,
                color: engagementColors[analysis.engagement_potential?.toLowerCase()]
              }}
            >
              {analysis.engagement_potential}
            </span>
          </div>
        </div>
      </div>

      {analysis.why && (
        <div className="mt-4 pt-4 border-t border-gray-800">
          <p className="text-gray-400 text-sm italic">"{analysis.why}"</p>
        </div>
      )}
    </div>
  )
}

// Reply Card with casino styling
function ReplyCard({ mode, reply, index }) {
  const { copied, copy } = useCopy()
  const config = MODES[mode] || MODES.card_counter
  const id = `reply-${mode}`

  return (
    <div
      className="bj-reply-card fade-in"
      style={{
        '--mode-color': config.color,
        animationDelay: `${index * 100}ms`
      }}
    >
      {/* Card edge decoration */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1 rounded-l-lg"
        style={{ backgroundColor: config.color }}
      />

      <div className="pl-5 pr-4 py-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center text-lg"
              style={{ backgroundColor: `${config.color}20` }}
            >
              {config.icon}
            </div>
            <div>
              <span
                className="font-semibold text-sm"
                style={{ color: config.color }}
              >
                {config.label}
              </span>
              <p className="text-xs text-gray-500">{config.pattern}</p>
            </div>
          </div>
          <span className="text-xs text-gray-600">{reply.length} chars</span>
        </div>

        <p className="text-gray-200 leading-relaxed mb-4" style={{ fontFamily: "'Inter', sans-serif" }}>
          {reply}
        </p>

        <div className="flex justify-between items-center">
          <span className={`text-xs ${reply.length <= 280 ? 'text-green-500' : 'text-red-400'}`}>
            {reply.length <= 280 ? '✓ Twitter ready' : '⚠ Over limit'}
          </span>
          <button
            onClick={() => copy(reply, id)}
            className={`bj-copy-btn ${copied === id ? 'copied' : ''}`}
          >
            {copied === id ? (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Copied
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                </svg>
                Copy
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// Tweet Card
function TweetCard({ tweet, index }) {
  const { copied, copy } = useCopy()
  const id = `tweet-${index}`

  return (
    <div className="bj-tweet-card fade-in" style={{ animationDelay: `${index * 100}ms` }}>
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center text-amber-400 font-bold text-sm flex-shrink-0">
          {index + 1}
        </div>
        <div className="flex-1">
          <p className="text-gray-200 leading-relaxed mb-3">{tweet.text}</p>
          <div className="flex justify-between items-center">
            <span className={`text-xs ${tweet.char_count <= 280 ? 'text-green-500' : 'text-red-400'}`}>
              {tweet.char_count} chars {tweet.char_count <= 280 && '✓'}
            </span>
            <button
              onClick={() => copy(tweet.text, id)}
              className={`bj-copy-btn ${copied === id ? 'copied' : ''}`}
            >
              {copied === id ? '✓ Copied' : 'Copy'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// Thread Card
function ThreadCard({ tweet, index, total }) {
  const { copied, copy } = useCopy()
  const id = `thread-${index}`
  const isFirst = index === 0
  const isLast = index === total - 1

  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center">
        <div
          className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm border-2
            ${isFirst ? 'bg-amber-500/20 border-amber-500 text-amber-400' :
              isLast ? 'bg-green-500/20 border-green-500 text-green-400' :
              'bg-gray-800 border-gray-700 text-gray-400'}`}
        >
          {index + 1}
        </div>
        {!isLast && (
          <div className="w-0.5 flex-1 bg-gradient-to-b from-gray-700 to-transparent my-2" />
        )}
      </div>

      <div className="bj-tweet-card flex-1 mb-4 fade-in" style={{ animationDelay: `${index * 100}ms` }}>
        <div className="flex items-center gap-2 mb-2">
          <span className={`text-xs font-semibold uppercase tracking-wider
            ${isFirst ? 'text-amber-400' : isLast ? 'text-green-400' : 'text-gray-500'}`}>
            {isFirst ? 'Hook' : isLast ? 'Closer' : 'Body'}
          </span>
        </div>
        <p className="text-gray-200 leading-relaxed mb-3">{tweet.text}</p>
        <div className="flex justify-between items-center">
          <span className="text-xs text-gray-500">{tweet.char_count} chars</span>
          <button
            onClick={() => copy(tweet.text, id)}
            className={`bj-copy-btn ${copied === id ? 'copied' : ''}`}
          >
            {copied === id ? '✓ Copied' : 'Copy'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Loading animation
function Loading({ message = "Reading the table..." }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-4">
      <div className="flex gap-2">
        {SUITS.map((suit, i) => (
          <span
            key={suit}
            className="text-2xl animate-bounce"
            style={{
              animationDelay: `${i * 150}ms`,
              color: i < 2 ? '#ef4444' : '#fafafa'
            }}
          >
            {suit}
          </span>
        ))}
      </div>
      <p className="text-gray-500 text-sm">{message}</p>
    </div>
  )
}

// Reply Generator Tab
function ReplyGenerator() {
  const [tweet, setTweet] = useState('')
  const [selectedMode, setSelectedMode] = useState(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const generate = async () => {
    if (!tweet.trim()) return

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch(`${API_BASE}/api/blackjack/replies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tweet: tweet.trim(),
          mode: selectedMode
        })
      })

      const data = await res.json()

      if (!res.ok) {
        throw new Error(data.detail || 'Failed to generate replies')
      }

      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="bj-input-card mb-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex gap-1">
            {SUITS.map((suit, i) => (
              <span key={suit} className={`text-lg ${i < 2 ? 'text-red-500' : 'text-white'}`}>{suit}</span>
            ))}
          </div>
          <div>
            <h2 className="font-semibold text-lg" style={{ fontFamily: "'Playfair Display', serif" }}>
              Reply Generator
            </h2>
            <p className="text-xs text-gray-500">Paste a tweet. Get gambling wisdom.</p>
          </div>
        </div>

        <textarea
          value={tweet}
          onChange={(e) => setTweet(e.target.value)}
          placeholder="Paste the tweet you want to reply to..."
          className="bj-textarea mb-4"
          rows={4}
        />

        {/* Mode Filter */}
        <div className="mb-4">
          <p className="text-xs text-gray-500 mb-2">Filter by mode (optional)</p>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setSelectedMode(null)}
              className={`bj-mode-chip ${selectedMode === null ? 'active' : ''}`}
            >
              All Modes
            </button>
            {Object.entries(MODES).map(([key, mode]) => (
              <button
                key={key}
                onClick={() => setSelectedMode(key)}
                className={`bj-mode-chip ${selectedMode === key ? 'active' : ''}`}
                style={{ '--chip-color': mode.color }}
              >
                <span>{mode.icon}</span>
                {mode.label}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={generate}
          disabled={!tweet.trim() || loading}
          className="bj-btn w-full"
        >
          {loading ? (
            <>
              <span className="animate-spin">♠</span>
              Dealing Cards...
            </>
          ) : (
            <>
              <span>🎰</span>
              Deal Replies
            </>
          )}
        </button>
      </div>

      {error && (
        <div className="bj-error mb-6 fade-in">
          <span className="text-red-400">♠</span> {error}
        </div>
      )}

      {loading && <Loading message="Counting cards..." />}

      {result && !loading && (
        <>
          <AnalysisPanel analysis={result.analysis} />

          <div className="flex items-center gap-2 mb-4">
            <ChipDeco size="sm" color="#f59e0b" />
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
              Your Plays
            </h3>
            <div className="flex-1 h-px bg-gradient-to-r from-gray-800 to-transparent" />
          </div>

          <div className="space-y-3">
            {result.replies?.map((r, i) => (
              <ReplyCard key={r.mode} mode={r.mode} reply={r.reply} index={i} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// Tweet Generator Tab
function TweetGenerator() {
  const [topic, setTopic] = useState('')
  const [count, setCount] = useState(5)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const generate = async () => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch(`${API_BASE}/api/blackjack/tweets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: topic.trim() || null,
          count
        })
      })

      const data = await res.json()

      if (!res.ok) {
        throw new Error(data.detail || 'Failed to generate tweets')
      }

      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="bj-input-card mb-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-amber-500/20 flex items-center justify-center">
            <span className="text-amber-400 text-xl">♦</span>
          </div>
          <div>
            <h2 className="font-semibold text-lg" style={{ fontFamily: "'Playfair Display', serif" }}>
              Tweet Generator
            </h2>
            <p className="text-xs text-gray-500">Deal fresh gambling wisdom</p>
          </div>
        </div>

        <input
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Topic (optional - leave empty for random wisdom)"
          className="bj-input mb-4"
        />

        <div className="mb-6">
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm text-gray-400">Number of tweets</span>
            <span className="text-lg font-bold text-amber-400">{count}</span>
          </div>
          <input
            type="range"
            min="1"
            max="10"
            value={count}
            onChange={(e) => setCount(parseInt(e.target.value))}
            className="bj-slider"
          />
          <div className="flex justify-between text-xs text-gray-600 mt-1">
            <span>1</span>
            <span>5</span>
            <span>10</span>
          </div>
        </div>

        <button onClick={generate} disabled={loading} className="bj-btn w-full">
          {loading ? (
            <>
              <span className="animate-spin">♦</span>
              Shuffling Deck...
            </>
          ) : (
            <>
              <span>✨</span>
              Deal Tweets
            </>
          )}
        </button>
      </div>

      {error && (
        <div className="bj-error mb-6 fade-in">
          <span className="text-red-400">♦</span> {error}
        </div>
      )}

      {loading && <Loading message="Shuffling the deck..." />}

      {result && !loading && (
        <>
          <div className="flex items-center gap-2 mb-4">
            <span className="text-amber-400">♦</span>
            <span className="text-sm text-gray-500">Topic: {result.topic}</span>
          </div>
          <div className="space-y-3">
            {result.tweets?.map((t, i) => (
              <TweetCard key={i} tweet={t} index={i} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// Thread Builder Tab
function ThreadBuilder() {
  const [topic, setTopic] = useState('')
  const [thesis, setThesis] = useState('')
  const [length, setLength] = useState(5)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const { copied, copy } = useCopy()

  const generate = async () => {
    if (!topic.trim()) return

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch(`${API_BASE}/api/blackjack/thread`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: topic.trim(),
          thesis: thesis.trim() || null,
          length
        })
      })

      const data = await res.json()

      if (!res.ok) {
        throw new Error(data.detail || 'Failed to generate thread')
      }

      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const copyAll = () => {
    if (!result?.tweets) return
    const text = result.tweets.map((t, i) => `${i + 1}/ ${t.text}`).join('\n\n')
    copy(text, 'all')
  }

  return (
    <div>
      <div className="bj-input-card mb-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-amber-500/20 flex items-center justify-center">
            <span className="text-amber-400 text-xl">♣</span>
          </div>
          <div>
            <h2 className="font-semibold text-lg" style={{ fontFamily: "'Playfair Display', serif" }}>
              Thread Builder
            </h2>
            <p className="text-xs text-gray-500">Stack the deck for maximum impact</p>
          </div>
        </div>

        <input
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Thread topic (required)"
          className="bj-input mb-3"
        />

        <input
          type="text"
          value={thesis}
          onChange={(e) => setThesis(e.target.value)}
          placeholder="Core thesis (optional)"
          className="bj-input mb-4"
        />

        <div className="mb-6">
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm text-gray-400">Thread length</span>
            <span className="text-lg font-bold text-amber-400">{length}</span>
          </div>
          <input
            type="range"
            min="3"
            max="12"
            value={length}
            onChange={(e) => setLength(parseInt(e.target.value))}
            className="bj-slider"
          />
          <div className="flex justify-between text-xs text-gray-600 mt-1">
            <span>3</span>
            <span>7</span>
            <span>12</span>
          </div>
        </div>

        <button
          onClick={generate}
          disabled={!topic.trim() || loading}
          className="bj-btn w-full"
        >
          {loading ? (
            <>
              <span className="animate-spin">♣</span>
              Stacking Deck...
            </>
          ) : (
            <>
              <span>🧵</span>
              Build Thread
            </>
          )}
        </button>
      </div>

      {error && (
        <div className="bj-error mb-6 fade-in">
          <span className="text-red-400">♣</span> {error}
        </div>
      )}

      {loading && <Loading message="Stacking the deck..." />}

      {result && !loading && (
        <>
          <div className="flex justify-between items-center mb-4">
            <div className="flex items-center gap-2">
              <span className="text-amber-400">♣</span>
              <span className="text-sm text-gray-500">{result.tweets?.length} tweets</span>
            </div>
            <button
              onClick={copyAll}
              className={`bj-copy-btn ${copied === 'all' ? 'copied' : ''}`}
            >
              {copied === 'all' ? '✓ Copied All' : 'Copy All'}
            </button>
          </div>

          <div>
            {result.tweets?.map((t, i) => (
              <ThreadCard
                key={i}
                tweet={t}
                index={i}
                total={result.tweets.length}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// Main Dashboard Component
export default function BlackjackDashboard() {
  const [tab, setTab] = useState('replies')
  const [status, setStatus] = useState(null)

  // Fetch status on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/blackjack/status`)
      .then(res => res.json())
      .then(data => setStatus(data))
      .catch(() => setStatus({ status: 'offline' }))
  }, [])

  return (
    <div className="min-h-screen bj-background">
      <FloatingSuits />

      {/* Header */}
      <header className="border-b border-gray-800/50 backdrop-blur-sm bg-black/30">
        <div className="max-w-3xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1 text-2xl">
                <span className="text-red-500">♥</span>
                <span className="text-white">♠</span>
              </div>
              <div>
                <h1
                  className="font-bold text-xl text-white"
                  style={{ fontFamily: "'Playfair Display', serif" }}
                >
                  Blackjack
                </h1>
                <p className="text-xs text-gray-500">Twitter Gambling Wisdom Engine</p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${status?.status === 'online' ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-xs text-gray-500">
                {status?.model || 'connecting...'}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <nav className="border-b border-gray-800/50 backdrop-blur-sm bg-black/20">
        <div className="max-w-3xl mx-auto px-4">
          <div className="flex gap-1 py-2">
            <button
              onClick={() => setTab('replies')}
              className={`bj-tab ${tab === 'replies' ? 'active' : ''}`}
            >
              <span className="text-red-500">♥</span> Replies
            </button>
            <button
              onClick={() => setTab('tweets')}
              className={`bj-tab ${tab === 'tweets' ? 'active' : ''}`}
            >
              <span className="text-amber-400">♦</span> Tweets
            </button>
            <button
              onClick={() => setTab('threads')}
              className={`bj-tab ${tab === 'threads' ? 'active' : ''}`}
            >
              <span className="text-white">♣</span> Threads
            </button>
          </div>
        </div>
      </nav>

      {/* Content */}
      <main className="max-w-3xl mx-auto px-4 py-6 relative z-10">
        {tab === 'replies' && <ReplyGenerator />}
        {tab === 'tweets' && <TweetGenerator />}
        {tab === 'threads' && <ThreadBuilder />}
      </main>

      {/* Footer tagline */}
      <footer className="text-center py-6 text-gray-600 text-xs">
        <p style={{ fontFamily: "'Playfair Display', serif" }}>
          "The house edge is ignorance. Your edge is wisdom."
        </p>
      </footer>

      {/* Blackjack-specific styles */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500;600;700&display=swap');

        .bj-background {
          background: linear-gradient(135deg, #0a0a0a 0%, #0f1419 50%, #0a0a0a 100%);
          background-attachment: fixed;
        }

        .bj-input-card {
          background: linear-gradient(145deg, #141414 0%, #1a1a1a 100%);
          border: 1px solid #2a2a2a;
          border-radius: 16px;
          padding: 24px;
          position: relative;
          overflow: hidden;
        }

        .bj-input-card::before {
          content: '';
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          height: 1px;
          background: linear-gradient(90deg, transparent, #f59e0b40, transparent);
        }

        .bj-textarea, .bj-input {
          background: #0a0a0a;
          border: 1px solid #2a2a2a;
          border-radius: 12px;
          padding: 14px 16px;
          color: #fafafa;
          font-size: 15px;
          width: 100%;
          transition: all 0.2s;
          resize: none;
        }

        .bj-textarea:focus, .bj-input:focus {
          outline: none;
          border-color: #f59e0b;
          box-shadow: 0 0 0 3px #f59e0b20;
        }

        .bj-textarea::placeholder, .bj-input::placeholder {
          color: #4a4a4a;
        }

        .bj-btn {
          background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
          color: #0a0a0a;
          font-weight: 600;
          padding: 14px 24px;
          border-radius: 12px;
          border: none;
          cursor: pointer;
          transition: all 0.2s;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          font-size: 15px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .bj-btn:hover {
          background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
          transform: translateY(-1px);
          box-shadow: 0 4px 20px #f59e0b40;
        }

        .bj-btn:disabled {
          background: #2a2a2a;
          color: #4a4a4a;
          cursor: not-allowed;
          transform: none;
          box-shadow: none;
        }

        .bj-tab {
          padding: 12px 20px;
          border-radius: 10px;
          border: none;
          background: transparent;
          color: #6b7280;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .bj-tab:hover {
          color: #fafafa;
          background: #1a1a1a;
        }

        .bj-tab.active {
          background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
          color: #0a0a0a;
        }

        .bj-mode-chip {
          padding: 8px 14px;
          border-radius: 20px;
          border: 1px solid #2a2a2a;
          background: #141414;
          color: #9ca3af;
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s;
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .bj-mode-chip:hover {
          border-color: var(--chip-color, #f59e0b);
          color: var(--chip-color, #f59e0b);
        }

        .bj-mode-chip.active {
          background: var(--chip-color, #f59e0b);
          border-color: var(--chip-color, #f59e0b);
          color: #0a0a0a;
        }

        .bj-analysis-panel {
          background: linear-gradient(145deg, #141414 0%, #1a1a1a 100%);
          border: 1px solid #2a2a2a;
          border-radius: 16px;
          padding: 20px;
          position: relative;
        }

        .bj-stat-box {
          background: #0a0a0a;
          border-radius: 10px;
          padding: 12px;
        }

        .bj-reply-card {
          background: linear-gradient(145deg, #141414 0%, #1a1a1a 100%);
          border: 1px solid #2a2a2a;
          border-radius: 12px;
          position: relative;
          overflow: hidden;
          transition: all 0.2s;
        }

        .bj-reply-card:hover {
          border-color: var(--mode-color, #f59e0b);
          transform: translateX(4px);
        }

        .bj-tweet-card {
          background: linear-gradient(145deg, #141414 0%, #1a1a1a 100%);
          border: 1px solid #2a2a2a;
          border-radius: 12px;
          padding: 16px;
          transition: all 0.2s;
        }

        .bj-tweet-card:hover {
          border-color: #f59e0b40;
        }

        .bj-copy-btn {
          padding: 8px 14px;
          border-radius: 8px;
          border: 1px solid #2a2a2a;
          background: #0a0a0a;
          color: #9ca3af;
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s;
          display: inline-flex;
          align-items: center;
          gap: 6px;
        }

        .bj-copy-btn:hover {
          background: #1a1a1a;
          border-color: #f59e0b;
          color: #f59e0b;
        }

        .bj-copy-btn.copied {
          background: #10b98120;
          border-color: #10b981;
          color: #10b981;
        }

        .bj-slider {
          -webkit-appearance: none;
          width: 100%;
          height: 6px;
          background: linear-gradient(90deg, #2a2a2a 0%, #f59e0b 100%);
          border-radius: 3px;
          cursor: pointer;
        }

        .bj-slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          width: 20px;
          height: 20px;
          background: #f59e0b;
          border-radius: 50%;
          cursor: pointer;
          box-shadow: 0 2px 10px #f59e0b40;
        }

        .bj-slider::-moz-range-thumb {
          width: 20px;
          height: 20px;
          background: #f59e0b;
          border-radius: 50%;
          border: none;
          cursor: pointer;
        }

        .bj-error {
          background: #7f1d1d20;
          border: 1px solid #7f1d1d;
          border-radius: 12px;
          padding: 14px 16px;
          color: #fca5a5;
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .fade-in {
          animation: fadeIn 0.4s ease-out;
        }

        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-8px); }
        }

        .animate-bounce {
          animation: bounce 1s ease-in-out infinite;
        }
      `}</style>
    </div>
  )
}
