import { MODES } from './ModeSelector'

// Status configuration
const STATUS_CONFIG = {
  stopped: {
    label: 'Stopped',
    color: '#6b7280',
    bgColor: 'rgba(107, 114, 128, 0.15)',
    pulse: false
  },
  running: {
    label: 'Running',
    color: '#22c55e',
    bgColor: 'rgba(34, 197, 94, 0.15)',
    pulse: true
  },
  paused: {
    label: 'Paused',
    color: '#eab308',
    bgColor: 'rgba(234, 179, 8, 0.15)',
    pulse: false
  },
  generating: {
    label: 'Generating...',
    color: '#f97316',
    bgColor: 'rgba(249, 115, 22, 0.15)',
    pulse: true
  }
}

// Find mode config by ID
function getModeConfig(modeId) {
  return Object.values(MODES).find(m => m.id === modeId) || MODES.PIRANHA
}

function StatusIndicator({ status }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.stopped

  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 rounded-full"
      style={{ background: config.bgColor }}
    >
      <span
        className={`w-2.5 h-2.5 rounded-full ${config.pulse ? 'animate-pulse' : ''}`}
        style={{ background: config.color }}
      />
      <span
        className="text-sm font-medium"
        style={{ color: config.color }}
      >
        {config.label}
      </span>
    </div>
  )
}

function ActionButton({ onClick, disabled, variant, children, icon }) {
  const variants = {
    start: {
      bg: 'bg-gradient-to-r from-green-600 to-emerald-600',
      hover: 'hover:from-green-700 hover:to-emerald-700',
      text: 'text-white'
    },
    stop: {
      bg: 'bg-gradient-to-r from-red-600 to-rose-600',
      hover: 'hover:from-red-700 hover:to-rose-700',
      text: 'text-white'
    },
    pause: {
      bg: 'bg-gradient-to-r from-yellow-600 to-amber-600',
      hover: 'hover:from-yellow-700 hover:to-amber-700',
      text: 'text-white'
    },
    resume: {
      bg: 'bg-gradient-to-r from-blue-600 to-indigo-600',
      hover: 'hover:from-blue-700 hover:to-indigo-700',
      text: 'text-white'
    },
    generate: {
      bg: 'bg-gradient-to-r from-orange-500 to-amber-500',
      hover: 'hover:from-orange-600 hover:to-amber-600',
      text: 'text-white'
    }
  }

  const v = variants[variant] || variants.start

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        px-4 py-2 rounded-lg font-semibold text-sm
        flex items-center gap-2 transition-all duration-200
        ${v.bg} ${v.hover} ${v.text}
        disabled:opacity-50 disabled:cursor-not-allowed
        shadow-md hover:shadow-lg active:scale-95
      `}
    >
      {icon && <span>{icon}</span>}
      {children}
    </button>
  )
}

export default function ControlPanel({
  status,
  currentMode,
  onStart,
  onStop,
  onPause,
  onResume,
  onGenerate,
  loading
}) {
  const modeConfig = getModeConfig(currentMode)
  const isStopped = status === 'stopped'
  const isRunning = status === 'running'
  const isPaused = status === 'paused'
  const isGenerating = status === 'generating'

  return (
    <div className="card p-4 mb-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Left side - Status and Mode */}
        <div className="flex items-center gap-4">
          <StatusIndicator status={status} />

          <div className="flex items-center gap-2">
            <span
              className="text-2xl"
              style={{ filter: 'drop-shadow(0 0 4px ' + modeConfig.color + ')' }}
            >
              {modeConfig.icon}
            </span>
            <div>
              <span
                className="font-bold"
                style={{ color: modeConfig.color }}
              >
                {modeConfig.label}
              </span>
              <span className="text-xs text-[var(--text-muted)] ml-2">
                ({modeConfig.timeframe})
              </span>
            </div>
          </div>
        </div>

        {/* Right side - Action Buttons */}
        <div className="flex items-center gap-2">
          {isStopped && (
            <ActionButton
              onClick={onStart}
              disabled={loading}
              variant="start"
              icon="▶"
            >
              Start
            </ActionButton>
          )}

          {(isRunning || isGenerating) && (
            <>
              <ActionButton
                onClick={onPause}
                disabled={loading || isGenerating}
                variant="pause"
                icon="⏸"
              >
                Pause
              </ActionButton>
              <ActionButton
                onClick={onStop}
                disabled={loading}
                variant="stop"
                icon="⏹"
              >
                Stop
              </ActionButton>
            </>
          )}

          {isPaused && (
            <>
              <ActionButton
                onClick={onResume}
                disabled={loading}
                variant="resume"
                icon="▶"
              >
                Resume
              </ActionButton>
              <ActionButton
                onClick={onStop}
                disabled={loading}
                variant="stop"
                icon="⏹"
              >
                Stop
              </ActionButton>
            </>
          )}

          {/* Manual generate button - always available when not stopped */}
          {!isStopped && (
            <ActionButton
              onClick={onGenerate}
              disabled={loading || isGenerating}
              variant="generate"
              icon="⚡"
            >
              Generate Now
            </ActionButton>
          )}
        </div>
      </div>
    </div>
  )
}
