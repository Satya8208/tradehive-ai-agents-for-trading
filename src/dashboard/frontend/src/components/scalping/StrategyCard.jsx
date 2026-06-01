import { useState } from 'react'
import { MODES } from './ModeSelector'

// Status configuration for validation results
const VALIDATION_STATUS = {
  approved: {
    label: 'Approved',
    icon: '✅',
    color: '#22c55e',
    bgColor: 'rgba(34, 197, 94, 0.1)',
    borderColor: 'rgba(34, 197, 94, 0.3)'
  },
  duplicate: {
    label: 'Duplicate',
    icon: '⚠️',
    color: '#eab308',
    bgColor: 'rgba(234, 179, 8, 0.1)',
    borderColor: 'rgba(234, 179, 8, 0.3)'
  },
  rejected: {
    label: 'Rejected',
    icon: '❌',
    color: '#ef4444',
    bgColor: 'rgba(239, 68, 68, 0.1)',
    borderColor: 'rgba(239, 68, 68, 0.3)'
  },
  pending: {
    label: 'Processing',
    icon: '⏳',
    color: '#6b7280',
    bgColor: 'rgba(107, 114, 128, 0.1)',
    borderColor: 'rgba(107, 114, 128, 0.3)'
  }
}

// Find mode config by ID
function getModeConfig(modeId) {
  return Object.values(MODES).find(m => m.id === modeId) || null
}

// Novelty score indicator
function NoveltyScore({ score }) {
  const percent = Math.round(score * 100)
  let color = '#ef4444' // red
  if (percent >= 40) color = '#eab308' // yellow
  if (percent >= 60) color = '#22c55e' // green
  if (percent >= 80) color = '#3b82f6' // blue

  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${percent}%`, background: color }}
        />
      </div>
      <span className="text-xs font-medium" style={{ color }}>
        {percent}%
      </span>
    </div>
  )
}

// Risk/Reward badge
function RiskRewardBadge({ ratio }) {
  const color = ratio >= 2 ? '#22c55e' : ratio >= 1.5 ? '#eab308' : '#ef4444'

  return (
    <span
      className="text-xs font-bold px-2 py-0.5 rounded"
      style={{ background: `${color}20`, color }}
    >
      R:R {ratio.toFixed(1)}:1
    </span>
  )
}

export default function StrategyCard({ strategy, isNew }) {
  const [expanded, setExpanded] = useState(false)

  const validationConfig = VALIDATION_STATUS[strategy.validation_status] || VALIDATION_STATUS.pending
  const modeConfig = getModeConfig(strategy.mode)

  // Parse timestamp
  const timestamp = new Date(strategy.timestamp)
  const timeAgo = getTimeAgo(timestamp)

  return (
    <div
      className={`
        card p-4 transition-all duration-300 cursor-pointer
        ${isNew ? 'animate-slideIn ring-2 ring-[var(--accent)] ring-opacity-50' : ''}
        hover:bg-[var(--bg-secondary)]
      `}
      style={{
        borderLeft: `3px solid ${validationConfig.color}`,
        background: validationConfig.bgColor
      }}
      onClick={() => setExpanded(!expanded)}
    >
      {/* Header row */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Validation status */}
          <span className="text-lg">{validationConfig.icon}</span>

          {/* Technique name */}
          <h3 className="font-semibold text-[var(--text-primary)]">
            {strategy.technique}
          </h3>

          {/* Mode badge */}
          {modeConfig && (
            <span
              className="text-xs px-2 py-0.5 rounded-full font-medium"
              style={{ background: modeConfig.bgGlow, color: modeConfig.color }}
            >
              {modeConfig.icon} {modeConfig.label}
            </span>
          )}
        </div>

        {/* Time ago */}
        <span className="text-xs text-[var(--text-muted)] shrink-0">
          {timeAgo}
        </span>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 text-sm">
        {/* Novelty */}
        <div className="flex items-center gap-2">
          <span className="text-[var(--text-muted)]">Novelty:</span>
          <NoveltyScore score={strategy.novelty_score} />
        </div>

        {/* Risk/Reward */}
        {strategy.risk_reward && (
          <RiskRewardBadge ratio={strategy.risk_reward} />
        )}

        {/* Source model */}
        {strategy.source_model && (
          <span className="text-xs text-[var(--text-muted)]">
            via {strategy.source_model}
          </span>
        )}

        {/* Expand indicator */}
        <span className="ml-auto text-[var(--text-muted)] text-xs">
          {expanded ? '▲ Collapse' : '▼ Details'}
        </span>
      </div>

      {/* Expanded content */}
      {expanded && strategy.full_content && (
        <div className="mt-4 pt-4 border-t border-[var(--border)]">
          <pre className="text-sm text-[var(--text-secondary)] whitespace-pre-wrap font-sans leading-relaxed">
            {strategy.full_content}
          </pre>
        </div>
      )}

      {/* Duplicate similarity note */}
      {strategy.validation_status === 'duplicate' && strategy.similarity && (
        <div className="mt-2 text-xs text-[var(--text-muted)]">
          {Math.round(strategy.similarity * 100)}% similar to existing strategy
        </div>
      )}
    </div>
  )
}

// Helper function to get relative time
function getTimeAgo(date) {
  const seconds = Math.floor((new Date() - date) / 1000)

  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}
