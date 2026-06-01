import { useState, useEffect, useCallback, useRef } from 'react'
import ModeSelector from './scalping/ModeSelector'
import ControlPanel from './scalping/ControlPanel'
import StrategyFeed from './scalping/StrategyFeed'
import StatsPanel from './scalping/StatsPanel'
import SettingsPanel from './scalping/SettingsPanel'

// API Base
const API_BASE = 'http://localhost:8010'

// Polling intervals
const STATUS_POLL_INTERVAL = 2000  // 2 seconds
const STRATEGY_POLL_INTERVAL = 3000  // 3 seconds

export default function ScalpingDashboard() {
  // State
  const [status, setStatus] = useState('stopped')
  const [currentMode, setCurrentMode] = useState('5m_contrarian') // VIPER default
  const [settings, setSettings] = useState({})
  const [stats, setStats] = useState({})
  const [techniques, setTechniques] = useState({})
  const [strategies, setStrategies] = useState([])
  const [newStrategyIds, setNewStrategyIds] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [connected, setConnected] = useState(false)

  // Refs for tracking
  const lastStrategyCount = useRef(0)
  const statusIntervalRef = useRef(null)
  const strategyIntervalRef = useRef(null)

  // Fetch agent status
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/scalping/status`)
      if (!res.ok) throw new Error('Failed to fetch status')

      const data = await res.json()
      setStatus(data.status)
      setCurrentMode(data.current_mode)
      setSettings(data.settings || {})
      setStats(data.stats || {})
      setConnected(true)
      setError(null)
    } catch (err) {
      setConnected(false)
      setError('Cannot connect to scalping API. Is the backend running?')
    }
  }, [])

  // Fetch strategies
  const fetchStrategies = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/scalping/strategies?limit=50`)
      if (!res.ok) throw new Error('Failed to fetch strategies')

      const data = await res.json()
      const newStrategies = data.strategies || []

      // Detect new strategies for animation
      if (newStrategies.length > lastStrategyCount.current) {
        const newIds = newStrategies
          .slice(0, newStrategies.length - lastStrategyCount.current)
          .map(s => s.id)
        setNewStrategyIds(newIds)

        // Clear new indicator after animation
        setTimeout(() => setNewStrategyIds([]), 3000)
      }
      lastStrategyCount.current = newStrategies.length

      setStrategies(newStrategies)
    } catch (err) {
      console.error('Error fetching strategies:', err)
    }
  }, [])

  // Fetch techniques performance
  const fetchTechniques = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/scalping/techniques`)
      if (!res.ok) return

      const data = await res.json()
      setTechniques(data.techniques || {})
    } catch (err) {
      console.error('Error fetching techniques:', err)
    }
  }, [])

  // Start polling
  useEffect(() => {
    // Initial fetch
    fetchStatus()
    fetchStrategies()
    fetchTechniques()

    // Set up polling
    statusIntervalRef.current = setInterval(fetchStatus, STATUS_POLL_INTERVAL)
    strategyIntervalRef.current = setInterval(fetchStrategies, STRATEGY_POLL_INTERVAL)

    // Cleanup
    return () => {
      if (statusIntervalRef.current) clearInterval(statusIntervalRef.current)
      if (strategyIntervalRef.current) clearInterval(strategyIntervalRef.current)
    }
  }, [fetchStatus, fetchStrategies, fetchTechniques])

  // Poll techniques less frequently
  useEffect(() => {
    const interval = setInterval(fetchTechniques, 10000)
    return () => clearInterval(interval)
  }, [fetchTechniques])

  // API Actions
  const apiAction = async (endpoint, method = 'POST', body = null) => {
    setLoading(true)
    setError(null)

    try {
      const options = {
        method,
        headers: { 'Content-Type': 'application/json' }
      }
      if (body) options.body = JSON.stringify(body)

      const res = await fetch(`${API_BASE}${endpoint}`, options)
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Action failed')
      }

      // Refresh status after action
      await fetchStatus()
      return true
    } catch (err) {
      setError(err.message)
      return false
    } finally {
      setLoading(false)
    }
  }

  // Action handlers
  const handleStart = () => apiAction('/api/scalping/start')
  const handleStop = () => apiAction('/api/scalping/stop')
  const handlePause = () => apiAction('/api/scalping/pause')
  const handleResume = () => apiAction('/api/scalping/resume')
  const handleGenerate = async () => {
    const success = await apiAction('/api/scalping/generate')
    if (success) {
      // Refresh strategies immediately after generating
      setTimeout(fetchStrategies, 1000)
    }
  }

  const handleModeChange = async (modeId) => {
    // Only allow mode change when stopped
    if (status !== 'stopped') {
      setError('Stop the agent before changing modes')
      return
    }
    await apiAction('/api/scalping/mode', 'POST', { mode: modeId })
  }

  const handleSettingsSave = async (newSettings) => {
    await apiAction('/api/scalping/settings', 'PATCH', newSettings)
  }

  return (
    <div className="min-h-screen bg-[var(--bg-primary)]">
      {/* Header */}
      <header className="border-b border-[var(--border)] bg-[var(--bg-secondary)]">
        <div className="max-w-6xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-3xl">🎯</span>
              <div>
                <h1 className="font-bold text-xl">Scalping Agent</h1>
                <p className="text-xs text-[var(--text-muted)]">
                  AI-Powered Strategy Generation
                </p>
              </div>
            </div>

            {/* Connection status */}
            <div className={`
              flex items-center gap-2 px-3 py-1.5 rounded-full text-sm
              ${connected
                ? 'bg-green-500/10 text-green-500'
                : 'bg-red-500/10 text-red-500'
              }
            `}>
              <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
              {connected ? 'Connected' : 'Disconnected'}
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-6xl mx-auto px-4 py-6">
        {/* Error banner */}
        {error && (
          <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 flex items-center justify-between">
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              className="text-red-400 hover:text-red-300"
            >
              ✕
            </button>
          </div>
        )}

        {/* Mode selector */}
        <ModeSelector
          currentMode={currentMode}
          onModeChange={handleModeChange}
          disabled={status !== 'stopped' || loading}
        />

        {/* Control panel */}
        <ControlPanel
          status={status}
          currentMode={currentMode}
          onStart={handleStart}
          onStop={handleStop}
          onPause={handlePause}
          onResume={handleResume}
          onGenerate={handleGenerate}
          loading={loading}
        />

        {/* Two-column layout for stats and settings on larger screens */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Strategy feed - takes 2 columns */}
          <div className="lg:col-span-2">
            <StrategyFeed
              strategies={strategies}
              isGenerating={status === 'generating'}
              newStrategyIds={newStrategyIds}
            />
          </div>

          {/* Stats and settings - 1 column */}
          <div className="space-y-6">
            <StatsPanel stats={stats} techniques={techniques} />
            <SettingsPanel
              settings={settings}
              onSave={handleSettingsSave}
              disabled={loading}
              loading={loading}
            />
          </div>
        </div>
      </main>
    </div>
  )
}
