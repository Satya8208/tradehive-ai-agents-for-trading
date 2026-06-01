import { useState, useEffect, useRef } from 'react'
import StrategyCard from './StrategyCard'

// Filter tabs
const FILTERS = [
  { id: 'all', label: 'All', icon: '📋' },
  { id: 'approved', label: 'Approved', icon: '✅' },
  { id: 'duplicate', label: 'Duplicates', icon: '⚠️' },
  { id: 'rejected', label: 'Rejected', icon: '❌' }
]

function FilterTabs({ activeFilter, onFilterChange }) {
  return (
    <div className="flex gap-1 mb-4 overflow-x-auto pb-2">
      {FILTERS.map(filter => (
        <button
          key={filter.id}
          onClick={() => onFilterChange(filter.id)}
          className={`
            px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap
            flex items-center gap-1.5 transition-all
            ${activeFilter === filter.id
              ? 'bg-[var(--accent)] text-white'
              : 'bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }
          `}
        >
          <span>{filter.icon}</span>
          <span>{filter.label}</span>
        </button>
      ))}
    </div>
  )
}

function GeneratingIndicator() {
  return (
    <div className="card p-4 mb-3 border-l-3 border-[var(--accent)] animate-pulse">
      <div className="flex items-center gap-3">
        <div className="relative">
          <span className="text-2xl">✨</span>
          <div className="absolute inset-0 animate-spin">
            <div className="w-full h-full rounded-full border-2 border-transparent border-t-[var(--accent)]" />
          </div>
        </div>
        <div>
          <span className="font-semibold text-[var(--accent)]">Generating new strategy...</span>
          <p className="text-xs text-[var(--text-muted)]">AI models are creating novel trading ideas</p>
        </div>
      </div>
    </div>
  )
}

function EmptyState({ filter }) {
  const messages = {
    all: 'No strategies generated yet. Start the agent to begin!',
    approved: 'No approved strategies yet. Keep generating!',
    duplicate: 'No duplicates found. Your strategies are unique!',
    rejected: 'No rejected strategies. Quality is looking good!'
  }

  return (
    <div className="text-center py-12 text-[var(--text-muted)]">
      <span className="text-4xl mb-4 block">📭</span>
      <p>{messages[filter] || messages.all}</p>
    </div>
  )
}

export default function StrategyFeed({ strategies, isGenerating, newStrategyIds }) {
  const [filter, setFilter] = useState('all')
  const feedRef = useRef(null)

  // Filter strategies
  const filteredStrategies = strategies.filter(s => {
    if (filter === 'all') return true
    return s.validation_status === filter
  })

  // Count by status
  const counts = {
    all: strategies.length,
    approved: strategies.filter(s => s.validation_status === 'approved').length,
    duplicate: strategies.filter(s => s.validation_status === 'duplicate').length,
    rejected: strategies.filter(s => s.validation_status === 'rejected').length
  }

  return (
    <div className="card p-4 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <span>📊</span>
          <span>Strategy Feed</span>
          <span className="text-sm font-normal text-[var(--text-muted)]">
            ({counts.all} total)
          </span>
        </h2>
      </div>

      {/* Filter tabs with counts */}
      <div className="flex gap-1 mb-4 overflow-x-auto pb-2">
        {FILTERS.map(f => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`
              px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap
              flex items-center gap-1.5 transition-all
              ${filter === f.id
                ? 'bg-[var(--accent)] text-white'
                : 'bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }
            `}
          >
            <span>{f.icon}</span>
            <span>{f.label}</span>
            <span className={`
              text-xs px-1.5 rounded-full
              ${filter === f.id ? 'bg-white/20' : 'bg-[var(--bg-card)]'}
            `}>
              {counts[f.id]}
            </span>
          </button>
        ))}
      </div>

      {/* Generating indicator */}
      {isGenerating && <GeneratingIndicator />}

      {/* Strategy list */}
      <div ref={feedRef} className="space-y-3 max-h-[500px] overflow-y-auto pr-2">
        {filteredStrategies.length === 0 ? (
          <EmptyState filter={filter} />
        ) : (
          filteredStrategies.map((strategy, index) => (
            <StrategyCard
              key={strategy.id || index}
              strategy={strategy}
              isNew={newStrategyIds?.includes(strategy.id)}
            />
          ))
        )}
      </div>
    </div>
  )
}
