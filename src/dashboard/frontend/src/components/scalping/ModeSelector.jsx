import { useState } from 'react'

// Mode configuration with icons and descriptions
const MODES = {
  PIRANHA: {
    id: '1m_hft',
    label: 'PIRANHA',
    icon: '🐟',
    timeframe: '1m',
    description: 'High-Frequency Trading',
    color: '#ef4444',
    bgGlow: 'rgba(239, 68, 68, 0.15)',
    features: ['Ultra-fast entries', 'Micro scalps', 'High volume']
  },
  SHARK: {
    id: '5m_momentum',
    label: 'SHARK',
    icon: '🦈',
    timeframe: '5m',
    description: 'Momentum Trading',
    color: '#3b82f6',
    bgGlow: 'rgba(59, 130, 246, 0.15)',
    features: ['Trend following', 'Breakout plays', 'Volume surges']
  },
  WHALE: {
    id: '15m_swing',
    label: 'WHALE',
    icon: '🐋',
    timeframe: '15m',
    description: 'Swing Trading',
    color: '#8b5cf6',
    bgGlow: 'rgba(139, 92, 246, 0.15)',
    features: ['Larger moves', 'Key levels', 'Patient entries']
  },
  VIPER: {
    id: '5m_contrarian',
    label: 'VIPER',
    icon: '🐍',
    timeframe: '5m',
    description: 'Contrarian Trading',
    color: '#10b981',
    bgGlow: 'rgba(16, 185, 129, 0.15)',
    features: ['Fade the crowd', 'Mean reversion', 'Sentiment plays']
  }
}

function ModeCard({ mode, isActive, onClick, disabled }) {
  const config = MODES[mode]

  return (
    <button
      onClick={() => onClick(config.id)}
      disabled={disabled}
      className={`
        relative overflow-hidden rounded-xl p-5 text-left transition-all duration-300
        border-2 cursor-pointer group
        ${isActive
          ? 'border-opacity-100 scale-[1.02] shadow-lg'
          : 'border-opacity-30 hover:border-opacity-60 hover:scale-[1.01]'
        }
        ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
      `}
      style={{
        borderColor: config.color,
        background: isActive ? config.bgGlow : 'var(--bg-card)'
      }}
    >
      {/* Active indicator pulse */}
      {isActive && (
        <div
          className="absolute top-3 right-3 w-3 h-3 rounded-full animate-pulse"
          style={{ background: config.color }}
        />
      )}

      {/* Mode icon and name */}
      <div className="flex items-center gap-3 mb-3">
        <span className="text-3xl filter drop-shadow-lg group-hover:scale-110 transition-transform">
          {config.icon}
        </span>
        <div>
          <h3
            className="font-bold text-lg tracking-wide"
            style={{ color: isActive ? config.color : 'var(--text-primary)' }}
          >
            {config.label}
          </h3>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full"
            style={{
              background: config.bgGlow,
              color: config.color
            }}>
            {config.timeframe}
          </span>
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-[var(--text-secondary)] mb-3">
        {config.description}
      </p>

      {/* Features */}
      <div className="flex flex-wrap gap-1">
        {config.features.map((feature, i) => (
          <span
            key={i}
            className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-secondary)] text-[var(--text-muted)]"
          >
            {feature}
          </span>
        ))}
      </div>

      {/* Hover glow effect */}
      <div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
        style={{
          background: `radial-gradient(circle at center, ${config.bgGlow} 0%, transparent 70%)`
        }}
      />
    </button>
  )
}

export default function ModeSelector({ currentMode, onModeChange, disabled }) {
  return (
    <div className="mb-6">
      <h2 className="text-sm font-semibold text-[var(--text-secondary)] mb-3 flex items-center gap-2">
        <span>Trading Mode</span>
        <span className="text-xs text-[var(--text-muted)]">Select your strategy style</span>
      </h2>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {Object.keys(MODES).map((mode) => (
          <ModeCard
            key={mode}
            mode={mode}
            isActive={currentMode === MODES[mode].id}
            onClick={onModeChange}
            disabled={disabled}
          />
        ))}
      </div>
    </div>
  )
}

export { MODES }
