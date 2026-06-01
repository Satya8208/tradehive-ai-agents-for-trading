import { useState } from 'react'

// Dynamic API Base for Poker
const getApiBase = () => {
    return 'http://localhost:8001'
}

// Position helper
const POSITIONS = ['UTG', 'UTG1', 'UTG2', 'MP', 'MP2', 'HJ', 'CO', 'BTN', 'SB', 'BB']

export default function PokerGod() {
  // State
  const [holeCards, setHoleCards] = useState('')
  const [board, setBoard] = useState('')
  const [potSize, setPotSize] = useState(10)
  const [betFacing, setBetFacing] = useState(0)
  const [position, setPosition] = useState('BTN')
  const [villainRange, setVillainRange] = useState('')
  
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const analyze = async () => {
    if (!holeCards.trim()) {
        setError("Enter hole cards (e.g. AhKh)")
        return
    }

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch(`${getApiBase()}/api/poker/advice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            hole_cards: holeCards,
            board: board,
            pot_size: Number(potSize),
            bet_facing: Number(betFacing),
            position: position,
            villain_range: villainRange || null
        })
      })

      const data = await res.json()

      if (!res.ok) {
        throw new Error(data.detail || 'Analysis failed')
      }

      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Helper to color cards
  const formatCards = (str) => {
    if (!str) return null
    return str.split(' ').map((card, i) => {
        const suit = card.slice(-1)
        const color = ['h', 'd'].includes(suit) ? 'text-red-500' : 'text-slate-200'
        return <span key={i} className={`font-mono font-bold ${color} mr-1`}>{card}</span>
    })
  }

  // Equity Gauge Component
  const EquityGauge = ({ value }) => {
    const percent = Math.round(value * 100)
    let color = 'bg-red-500'
    if (percent > 40) color = 'bg-yellow-500'
    if (percent > 60) color = 'bg-green-500'

    return (
        <div className="w-full bg-slate-700 h-4 rounded-full overflow-hidden mt-2 relative">
            <div 
                className={`h-full ${color} transition-all duration-500`} 
                style={{ width: `${percent}%` }}
            />
            <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-white shadow-black drop-shadow-md">
                {percent}% Equity
            </span>
        </div>
    )
  }

  return (
    <div>
      <div className="card p-6 mb-6">
        <h2 className="text-lg font-semibold mb-1 flex items-center gap-2">
            <span>🎰</span> Poker God Mode
        </h2>
        <p className="text-sm text-[var(--text-muted)] mb-6">
            GTO + Exploitative Analysis with Monte Carlo Equity
        </p>

        {/* Inputs Grid */}
        <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
                <label className="text-xs text-[var(--text-muted)] block mb-1">Hole Cards</label>
                <input
                    type="text"
                    value={holeCards}
                    onChange={(e) => setHoleCards(e.target.value)}
                    placeholder="Ah Kh"
                    className="input font-mono text-center uppercase"
                />
            </div>
            <div>
                <label className="text-xs text-[var(--text-muted)] block mb-1">Board</label>
                <input
                    type="text"
                    value={board}
                    onChange={(e) => setBoard(e.target.value)}
                    placeholder="Ks 7c 2d"
                    className="input font-mono text-center uppercase"
                />
            </div>
        </div>

        <div className="grid grid-cols-3 gap-4 mb-4">
            <div>
                <label className="text-xs text-[var(--text-muted)] block mb-1">Pot Size (BB)</label>
                <input
                    type="number"
                    value={potSize}
                    onChange={(e) => setPotSize(e.target.value)}
                    className="input text-center"
                />
            </div>
            <div>
                <label className="text-xs text-[var(--text-muted)] block mb-1">Bet Facing (BB)</label>
                <input
                    type="number"
                    value={betFacing}
                    onChange={(e) => setBetFacing(e.target.value)}
                    className="input text-center"
                />
            </div>
            <div>
                <label className="text-xs text-[var(--text-muted)] block mb-1">Position</label>
                <select 
                    value={position} 
                    onChange={(e) => setPosition(e.target.value)}
                    className="input text-center"
                >
                    {POSITIONS.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
            </div>
        </div>

        <div className="mb-6">
            <label className="text-xs text-[var(--text-muted)] block mb-1">Villain Range (Optional)</label>
            <input
                type="text"
                value={villainRange}
                onChange={(e) => setVillainRange(e.target.value)}
                placeholder="22+, A2s+, KQs"
                className="input font-mono text-sm"
            />
            <p className="text-[10px] text-[var(--text-muted)] mt-1">
                Enter simple range or leave blank for estimate.
            </p>
        </div>

        <button 
            onClick={analyze} 
            disabled={loading} 
            className="btn w-full bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 border-none"
        >
            {loading ? 'Crunching Numbers...' : '🧠 Ask The God'}
        </button>
      </div>

      {error && (
        <div className="card p-4 mb-6 border-red-500/50 bg-red-500/10 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div className="card p-6 fade-in border-t-4 border-t-purple-500">
            {/* Action Header */}
            <div className="text-center mb-6">
                <span className="text-xs uppercase tracking-widest text-[var(--text-muted)]">Recommendation</span>
                <div className="text-4xl font-black text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-blue-400 mt-2">
                    {result.decision.replace('_', ' ')}
                </div>
                {result.sizing && (
                    <div className="text-lg font-bold text-[var(--text-secondary)] mt-1">
                        Size: {Math.round(result.sizing * 100)}% Pot
                    </div>
                )}
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-2 gap-4 mb-6">
                <div className="bg-[var(--bg-secondary)] p-3 rounded-lg text-center">
                    <span className="text-xs text-[var(--text-muted)]">Hand Strength</span>
                    <div className="font-bold text-[var(--accent)] capitalize">
                        {result.hand_class.replace('_', ' ')}
                    </div>
                </div>
                <div className="bg-[var(--bg-secondary)] p-3 rounded-lg text-center">
                    <span className="text-xs text-[var(--text-muted)]">Equity</span>
                    <div className="font-bold text-[var(--text-primary)]">
                        <EquityGauge value={result.equity} />
                    </div>
                </div>
            </div>

            {/* Reasoning */}
            <div className="bg-[var(--bg-secondary)] p-4 rounded-lg border-l-4 border-purple-500/50">
                <span className="text-xs uppercase tracking-widest text-[var(--text-muted)] block mb-2">God's Wisdom</span>
                <p className="text-sm leading-relaxed text-[var(--text-primary)] italic">
                    "{result.reasoning}"
                </p>
            </div>
        </div>
      )}
    </div>
  )
}
