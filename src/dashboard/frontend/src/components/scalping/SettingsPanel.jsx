import { useState, useEffect } from 'react'

function Toggle({ label, checked, onChange, disabled }) {
  return (
    <label className={`flex items-center justify-between cursor-pointer ${disabled ? 'opacity-50' : ''}`}>
      <span className="text-sm text-[var(--text-secondary)]">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`
          relative inline-flex h-6 w-11 items-center rounded-full transition-colors
          ${checked ? 'bg-[var(--accent)]' : 'bg-[var(--border)]'}
          ${disabled ? 'cursor-not-allowed' : 'cursor-pointer'}
        `}
      >
        <span
          className={`
            inline-block h-4 w-4 transform rounded-full bg-white shadow-md transition-transform
            ${checked ? 'translate-x-6' : 'translate-x-1'}
          `}
        />
      </button>
    </label>
  )
}

function SliderInput({ label, value, onChange, min, max, step, suffix, disabled }) {
  return (
    <div className={disabled ? 'opacity-50' : ''}>
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm text-[var(--text-secondary)]">{label}</span>
        <span className="text-sm font-bold text-[var(--accent)]">
          {value}{suffix}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        disabled={disabled}
        className="w-full"
      />
      <div className="flex justify-between text-xs text-[var(--text-muted)] mt-1">
        <span>{min}{suffix}</span>
        <span>{max}{suffix}</span>
      </div>
    </div>
  )
}

function NumberInput({ label, value, onChange, min, max, suffix, disabled }) {
  return (
    <div className={disabled ? 'opacity-50' : ''}>
      <label className="text-sm text-[var(--text-secondary)] block mb-2">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          min={min}
          max={max}
          disabled={disabled}
          className="input text-center w-24"
        />
        {suffix && <span className="text-sm text-[var(--text-muted)]">{suffix}</span>}
      </div>
    </div>
  )
}

export default function SettingsPanel({ settings, onSave, disabled, loading }) {
  const [expanded, setExpanded] = useState(false)
  const [localSettings, setLocalSettings] = useState(settings || {})
  const [hasChanges, setHasChanges] = useState(false)

  // Sync with prop changes
  useEffect(() => {
    setLocalSettings(settings || {})
    setHasChanges(false)
  }, [settings])

  // Track changes
  const updateSetting = (key, value) => {
    setLocalSettings(prev => ({ ...prev, [key]: value }))
    setHasChanges(true)
  }

  // Save handler
  const handleSave = () => {
    onSave(localSettings)
    setHasChanges(false)
  }

  // Reset handler
  const handleReset = () => {
    setLocalSettings(settings || {})
    setHasChanges(false)
  }

  return (
    <div className="card overflow-hidden mb-6">
      {/* Header - Clickable */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 flex items-center justify-between text-left hover:bg-[var(--bg-secondary)] transition-colors"
      >
        <div className="flex items-center gap-2">
          <span>⚙️</span>
          <span className="font-semibold">Settings</span>
          {hasChanges && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-[var(--accent)]/20 text-[var(--accent)]">
              Unsaved
            </span>
          )}
        </div>
        <span className="text-[var(--text-muted)]">
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {/* Expandable content */}
      {expanded && (
        <div className="p-4 pt-0 border-t border-[var(--border)]">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
            {/* Left column - Number inputs */}
            <div className="space-y-6">
              <NumberInput
                label="Generation Interval"
                value={localSettings.generation_interval || 60}
                onChange={(v) => updateSetting('generation_interval', v)}
                min={10}
                max={300}
                suffix="seconds"
                disabled={disabled}
              />

              <NumberInput
                label="Min Risk/Reward Ratio"
                value={localSettings.min_risk_reward || 2.0}
                onChange={(v) => updateSetting('min_risk_reward', v)}
                min={1.0}
                max={5.0}
                suffix=":1"
                disabled={disabled}
              />

              <SliderInput
                label="Novelty Threshold"
                value={localSettings.novelty_threshold || 0.4}
                onChange={(v) => updateSetting('novelty_threshold', v)}
                min={0.1}
                max={0.9}
                step={0.05}
                suffix=""
                disabled={disabled}
              />
            </div>

            {/* Right column - Toggles */}
            <div className="space-y-4">
              <Toggle
                label="Parallel Mode (All AI models)"
                checked={localSettings.parallel_mode ?? true}
                onChange={(v) => updateSetting('parallel_mode', v)}
                disabled={disabled}
              />

              <Toggle
                label="Skip Consensus (Faster)"
                checked={localSettings.skip_consensus ?? false}
                onChange={(v) => updateSetting('skip_consensus', v)}
                disabled={disabled}
              />

              <Toggle
                label="Auto-save Strategies"
                checked={localSettings.auto_save ?? true}
                onChange={(v) => updateSetting('auto_save', v)}
                disabled={disabled}
              />

              <div className="text-xs text-[var(--text-muted)] mt-4 p-3 bg-[var(--bg-secondary)] rounded-lg">
                <strong>Parallel Mode:</strong> Uses all AI models simultaneously for diverse ideas.<br />
                <strong>Skip Consensus:</strong> Skip multi-model validation for speed.
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-[var(--border)]">
            <button
              onClick={handleReset}
              disabled={!hasChanges || disabled || loading}
              className="px-4 py-2 rounded-lg text-sm font-medium
                bg-[var(--bg-secondary)] text-[var(--text-secondary)]
                hover:bg-[var(--border)] disabled:opacity-50 disabled:cursor-not-allowed
                transition-colors"
            >
              Reset
            </button>
            <button
              onClick={handleSave}
              disabled={!hasChanges || disabled || loading}
              className="px-4 py-2 rounded-lg text-sm font-medium
                bg-[var(--accent)] text-white
                hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed
                transition-colors"
            >
              {loading ? 'Saving...' : 'Save Settings'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
