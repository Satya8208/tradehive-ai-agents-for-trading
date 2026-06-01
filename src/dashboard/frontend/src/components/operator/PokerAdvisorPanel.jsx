import { useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'tradehive-operator-poker'

const DEFAULT_SPOT = {
  hole_cards: 'Ah Kh',
  board: 'Qs 7c 2d',
  position: 'BTN',
  villain_type: 'reg',
  villain_position: 'CO',
  pot_size: 12,
  bet_to_call: 4,
  effective_stack: 100,
  is_preflop_aggressor: true,
}

const DEFAULT_ACTION_HISTORY = 'open 2.5bb\nbb call\nflop cbet 33%'

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw
      ? JSON.parse(raw)
      : { spot: DEFAULT_SPOT, bookmarkNote: '', actionHistoryText: DEFAULT_ACTION_HISTORY }
  } catch {
    return { spot: DEFAULT_SPOT, bookmarkNote: '', actionHistoryText: DEFAULT_ACTION_HISTORY }
  }
}

const POSITIONS = ['UTG', 'UTG1', 'UTG2', 'MP', 'MP2', 'HJ', 'CO', 'BTN', 'SB', 'BB']
const VILLAIN_TYPES = ['reg', 'fish', 'tag', 'lag', 'nit']

function parseActionHistory(text) {
  return text.split('\n').map((item) => item.trim()).filter(Boolean)
}

function hydrateStateFromSpot(spot) {
  return {
    hole_cards: spot.hole_cards || '',
    board: spot.board || '',
    position: spot.position || 'BTN',
    villain_type: spot.villain_type || 'reg',
    villain_position: spot.villain_position || '',
    pot_size: spot.pot_size ?? 1.5,
    bet_to_call: spot.bet_to_call ?? 0,
    effective_stack: spot.effective_stack ?? 100,
    is_preflop_aggressor: spot.is_preflop_aggressor ?? true,
  }
}

function formatTime(isoStr) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    const now = new Date()
    const isToday = d.toDateString() === now.toDateString()
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    if (isToday) return `Today ${time}`
    return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`
  } catch {
    return isoStr
  }
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'n/a'
  return `${Math.round(Number(value) * 100)}%`
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('Failed to read screenshot file'))
    reader.readAsDataURL(file)
  })
}

function formatVisibleCards(opponent) {
  if (!opponent?.cards?.length) return 'unknown'
  return opponent.cards.join(' ')
}

function cloneSnapshot(value) {
  if (value === null || value === undefined) return value
  return JSON.parse(JSON.stringify(value))
}

export default function PokerAdvisorPanel({ apiBase, onQueueChange }) {
  const [uiState, setUiState] = useState(loadState)
  const [analysis, setAnalysis] = useState(null)
  const [analysisSource, setAnalysisSource] = useState(null)
  const [screenshotResult, setScreenshotResult] = useState(null)
  const [screenshotState, setScreenshotState] = useState({
    imageData: '',
    imageType: 'image/png',
    fileName: '',
    previewUrl: '',
  })
  const [queue, setQueue] = useState([])
  const [selectedReview, setSelectedReview] = useState(null)
  const [selectedReviewId, setSelectedReviewId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [screenshotLoading, setScreenshotLoading] = useState(false)
  const [removingId, setRemovingId] = useState(null)
  const [error, setError] = useState(null)
  const analysisRef = useRef(null)
  const fileInputRef = useRef(null)
  const screenshotZoneRef = useRef(null)
  const manualSnapshotRef = useRef(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(uiState))
  }, [uiState])

  useEffect(() => {
    onQueueChange?.(queue.length)
  }, [queue.length, onQueueChange])

  const loadQueue = async () => {
    const response = await fetch(`${apiBase}/api/poker/review-queue`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Failed to load review queue')
    setQueue(data.items || [])
  }

  const loadReviewItem = async (id) => {
    setSelectedReviewId(id)
    const response = await fetch(`${apiBase}/api/poker/review-queue/${id}`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Failed to load review packet')
    setSelectedReview(data)
  }

  useEffect(() => {
    loadQueue().catch((queueError) => setError(queueError.message))
  }, [apiBase])

  const updateSpot = (field, value) => {
    setUiState((current) => ({
      ...current,
      spot: { ...current.spot, [field]: value },
    }))
  }

  const applySpotToForm = (spot) => {
    if (!spot) return
    setUiState((current) => ({
      ...current,
      spot: hydrateStateFromSpot(spot),
      actionHistoryText: (spot.action_history || []).join('\n'),
    }))
  }

  const scrollToAnalysis = () => {
    setTimeout(() => analysisRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
  }

  const rememberManualSnapshot = () => {
    if (manualSnapshotRef.current) return
    manualSnapshotRef.current = {
      uiState: cloneSnapshot(uiState),
      analysis: cloneSnapshot(analysis),
      analysisSource,
    }
  }

  const analyzeSpot = async () => {
    setLoading(true)
    setError(null)
    try {
      const payload = {
        ...uiState.spot,
        pot_size: Number(uiState.spot.pot_size),
        bet_to_call: Number(uiState.spot.bet_to_call),
        effective_stack: Number(uiState.spot.effective_stack),
        action_history: parseActionHistory(uiState.actionHistoryText),
      }
      const response = await fetch(`${apiBase}/api/poker/advisor/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Failed to analyze poker spot')
      setAnalysis(data)
      setAnalysisSource('manual')
      scrollToAnalysis()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const analyzeScreenshot = async (imageData = screenshotState.imageData, imageType = screenshotState.imageType) => {
    if (!imageData) return
    rememberManualSnapshot()
    setScreenshotLoading(true)
    setError(null)
    try {
      const response = await fetch(`${apiBase}/api/poker/advisor/analyze-screenshot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_data: imageData,
          image_type: imageType,
          source_hint: 'online_table_ui',
        }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Failed to analyze screenshot')
      setScreenshotResult(data)
      if (data.parsed_spot) {
        applySpotToForm(data.parsed_spot)
      }
      setAnalysis(data.decision ? data : null)
      setAnalysisSource(data.decision ? 'screenshot' : null)
      scrollToAnalysis()
    } catch (requestError) {
      setScreenshotResult(null)
      setAnalysis(null)
      setAnalysisSource(null)
      setError(requestError.message)
    } finally {
      setScreenshotLoading(false)
    }
  }

  const loadScreenshotFile = async (file) => {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('Only image screenshots are supported.')
      return
    }
    const dataUrl = await readFileAsDataUrl(file)
    setError(null)
    setScreenshotState({
      imageData: dataUrl,
      imageType: file.type || 'image/png',
      fileName: file.name || 'pasted-screenshot.png',
      previewUrl: dataUrl,
    })
    await analyzeScreenshot(dataUrl, file.type || 'image/png')
  }

  const resetScreenshot = () => {
    setScreenshotState({
      imageData: '',
      imageType: 'image/png',
      fileName: '',
      previewUrl: '',
    })
    setScreenshotResult(null)
    setError(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }

    if (manualSnapshotRef.current) {
      setUiState(manualSnapshotRef.current.uiState)
      setAnalysis(manualSnapshotRef.current.analysis)
      setAnalysisSource(manualSnapshotRef.current.analysisSource || null)
      manualSnapshotRef.current = null
      return
    }

    if (analysisSource === 'screenshot') {
      setAnalysis(null)
      setAnalysisSource(null)
    }
  }

  const handleScreenshotPaste = async (event) => {
    const items = Array.from(event.clipboardData?.items || [])
    const imageItem = items.find((item) => item.type.startsWith('image/'))
    if (!imageItem) return
    event.preventDefault()
    const file = imageItem.getAsFile()
    if (!file) return
    try {
      await loadScreenshotFile(file)
    } catch (pasteError) {
      setError(pasteError.message)
    }
  }

  const openScreenshotPicker = () => {
    fileInputRef.current?.click()
  }

  const handleScreenshotZoneClick = (event) => {
    if (event.target instanceof HTMLElement && event.target.closest('button, input')) return
    openScreenshotPicker()
  }

  const bookmarkSpot = async () => {
    if (!analysis?.decision) return
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`${apiBase}/api/poker/review-queue`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label: `${uiState.spot.hole_cards} · ${analysis.decision.action.toUpperCase()}`,
          note: uiState.bookmarkNote,
          spot: analysis.spot,
          decision: analysis.decision,
        }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Failed to save review item')
      setQueue((current) => [data, ...current])
      setUiState((current) => ({ ...current, bookmarkNote: '' }))
      await loadReviewItem(data.id)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const removeQueueItem = async (id) => {
    setRemovingId(id)
    try {
      const response = await fetch(`${apiBase}/api/poker/review-queue/${id}`, { method: 'DELETE' })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Failed to delete review item')
      setQueue((current) => current.filter((item) => item.id !== id))
      if (selectedReviewId === id) {
        setSelectedReview(null)
        setSelectedReviewId(null)
      }
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setRemovingId(null)
    }
  }

  const replaySelected = () => {
    if (!selectedReview?.item?.spot) return
    applySpotToForm(selectedReview.item.spot)
  }

  const screenshotStatus = screenshotResult?.decision_status || 'neutral'
  const screenshotHeadline = screenshotResult?.decision
    ? screenshotResult.decision.action.replaceAll('_', ' ')
    : screenshotStatus === 'blocked'
      ? 'Needs confirmation'
      : 'Screenshot ready'

  return (
    <div className="operator-section-grid">
      <section className="panel card">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Live state</p>
            <h2 className="panel-title">Poker Advisor</h2>
          </div>
          <button className="btn" onClick={analyzeSpot} disabled={loading || screenshotLoading}>
            {loading ? 'Analyzing…' : 'Analyze Spot'}
          </button>
        </div>

        <div
          ref={screenshotZoneRef}
          className={`screenshot-zone ${screenshotLoading ? 'is-loading' : ''}`}
          role="button"
          tabIndex={0}
          aria-label="Paste, drop, or upload a poker table screenshot"
          aria-busy={screenshotLoading}
          onClick={handleScreenshotZoneClick}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              openScreenshotPicker()
            }
          }}
          onPaste={handleScreenshotPaste}
          onDragOver={(event) => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'copy'
          }}
          onDrop={async (event) => {
            event.preventDefault()
            const [file] = Array.from(event.dataTransfer.files || [])
            try {
              await loadScreenshotFile(file)
            } catch (dropError) {
              setError(dropError.message)
            }
          }}
        >
          <div className="screenshot-copy">
            <p className="panel-kicker">Screenshot mode</p>
            <h3>Drop or paste an online table screenshot</h3>
            <p>
              The parser reads visible cards, stacks, and bets, then sends the structured spot through the existing
              advisor for a quick decision.
            </p>
            <p className="screenshot-hint">Click, drop, or press Ctrl+V while this box is focused.</p>
          </div>

          <div className="screenshot-actions">
            <button className="ghost-btn" onClick={openScreenshotPicker} type="button">
              Upload screenshot
            </button>
            <button
              className="ghost-btn"
              onClick={() => analyzeScreenshot()}
              disabled={!screenshotState.imageData || screenshotLoading}
              type="button"
            >
              {screenshotLoading ? 'Parsing…' : 'Analyze screenshot'}
            </button>
            <button
              className="ghost-btn"
              onClick={resetScreenshot}
              disabled={!screenshotState.imageData && !screenshotResult}
              type="button"
            >
              Reset
            </button>
            <input
              ref={fileInputRef}
              className="hidden-file-input"
              type="file"
              accept="image/*"
              onChange={async (event) => {
                const [file] = Array.from(event.target.files || [])
                try {
                  await loadScreenshotFile(file)
                } catch (fileError) {
                  setError(fileError.message)
                } finally {
                  event.target.value = ''
                }
              }}
            />
          </div>

          {screenshotState.previewUrl && (
            <div className="screenshot-preview-wrap">
              <img className="screenshot-preview" src={screenshotState.previewUrl} alt="Poker screenshot preview" />
              <p className="subcard-copy">
                {screenshotState.fileName || 'Clipboard image'} · focus this box and press Ctrl+V, or drop a new screenshot to re-run.
              </p>
            </div>
          )}
        </div>

        {screenshotResult && (
          <div className="strategy-card compact">
            <div className="strategy-head">
              <div>
                <p className="panel-kicker">Quick decision</p>
                <h3>{screenshotHeadline}</h3>
              </div>
              <span className={`metric-badge ${screenshotStatus}`}>{screenshotStatus}</span>
            </div>

            <div className="operator-card-grid">
              <article className="subcard">
                <p className="subcard-title">Parse confidence</p>
                <div className="subcard-metric">{formatPercent(screenshotResult.parse_confidence)}</div>
                <p className="subcard-copy">{screenshotResult.parsed_spot?.source_hint || 'online_table_ui'}</p>
              </article>
              <article className="subcard">
                <p className="subcard-title">Detected spot</p>
                <div className="subcard-metric">{screenshotResult.parsed_spot?.hole_cards || 'n/a'}</div>
                <p className="subcard-copy">
                  {screenshotResult.parsed_spot?.board || 'preflop'} · {screenshotResult.parsed_spot?.position || 'unknown'}
                </p>
              </article>
              <article className="subcard">
                <p className="subcard-title">Advisor action</p>
                <div className="subcard-metric">
                  {screenshotResult.decision ? screenshotResult.decision.action.replaceAll('_', ' ') : 'blocked'}
                </div>
                <p className="subcard-copy">
                  {screenshotResult.decision ? `${screenshotResult.spot?.street || screenshotResult.decision.street}` : 'Fix warnings below'}
                </p>
              </article>
            </div>

            <div className="list-block">
              <h3>Parsed screenshot</h3>
              <p>
                Hero: {screenshotResult.parsed_spot?.hole_cards || 'unknown'} · Board: {screenshotResult.parsed_spot?.board || 'preflop'}
              </p>
              <p className="subcard-copy">
                Pot {screenshotResult.parsed_spot?.pot_size ?? 'n/a'}bb · To call {screenshotResult.parsed_spot?.bet_to_call ?? 'n/a'}bb · Stack {screenshotResult.parsed_spot?.effective_stack ?? 'n/a'}bb
              </p>
              <p className="subcard-copy">
                Button {screenshotResult.parsed_spot?.button_position || 'unknown'} · Villain position {screenshotResult.parsed_spot?.villain_position || 'unknown'}
              </p>
            </div>

            {!!screenshotResult.visible_opponents?.length && (
              <div className="list-block">
                <h3>Visible opponents</h3>
                <div className="queue-list">
                  {screenshotResult.visible_opponents.map((opponent, index) => (
                    <article className="queue-item static" key={`${opponent.seat}-${index}`}>
                      <div className="queue-open">
                        <span className="queue-title">{opponent.seat}</span>
                        <span className="queue-meta">{opponent.position || 'position unknown'}</span>
                        <span className="queue-note">{formatVisibleCards(opponent)}</span>
                        {opponent.note && <span className="queue-note">{opponent.note}</span>}
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            )}

            {!!screenshotResult.missing_fields?.length && (
              <div className="list-block">
                <h3>Missing fields</h3>
                <ul>
                  {screenshotResult.missing_fields.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
            )}

            {!!screenshotResult.warnings?.length && (
              <div className="list-block">
                <h3>Screenshot warnings</h3>
                <ul>
                  {screenshotResult.warnings.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="bookmark-row">
              <button className="ghost-btn" onClick={() => applySpotToForm(screenshotResult.parsed_spot)} type="button">
                Load into manual form
              </button>
            </div>
          </div>
        )}

        <div className="field-grid three">
          <div>
            <label className="field-label">Hole cards</label>
            <input className="input" value={uiState.spot.hole_cards} onChange={(event) => updateSpot('hole_cards', event.target.value)} />
          </div>
          <div>
            <label className="field-label">Board</label>
            <input className="input" value={uiState.spot.board} onChange={(event) => updateSpot('board', event.target.value)} />
          </div>
          <div>
            <label className="field-label">Position</label>
            <select className="input operator-select" value={uiState.spot.position} onChange={(event) => updateSpot('position', event.target.value)}>
              {POSITIONS.map((position) => (
                <option key={position} value={position}>{position}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="field-label">Villain type</label>
            <select className="input operator-select" value={uiState.spot.villain_type} onChange={(event) => updateSpot('villain_type', event.target.value)}>
              {VILLAIN_TYPES.map((villain) => (
                <option key={villain} value={villain}>{villain}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">Villain position</label>
            <select className="input operator-select" value={uiState.spot.villain_position} onChange={(event) => updateSpot('villain_position', event.target.value)}>
              <option value="">unknown</option>
              {POSITIONS.map((position) => (
                <option key={position} value={position}>{position}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">Preflop aggressor</label>
            <select className="input operator-select" value={uiState.spot.is_preflop_aggressor ? 'yes' : 'no'} onChange={(event) => updateSpot('is_preflop_aggressor', event.target.value === 'yes')}>
              <option value="yes">hero</option>
              <option value="no">villain</option>
            </select>
          </div>

          <div>
            <label className="field-label">Pot (bb)</label>
            <input className="input" type="number" value={uiState.spot.pot_size} onChange={(event) => updateSpot('pot_size', event.target.value)} />
          </div>
          <div>
            <label className="field-label">To call (bb)</label>
            <input className="input" type="number" value={uiState.spot.bet_to_call} onChange={(event) => updateSpot('bet_to_call', event.target.value)} />
          </div>
          <div>
            <label className="field-label">Effective stack (bb)</label>
            <input className="input" type="number" value={uiState.spot.effective_stack} onChange={(event) => updateSpot('effective_stack', event.target.value)} />
          </div>
        </div>

        <div className="list-block">
          <h3>Action history</h3>
          <textarea
            className="input operator-textarea"
            spellCheck={false}
            value={uiState.actionHistoryText}
            onChange={(event) => setUiState((current) => ({ ...current, actionHistoryText: event.target.value }))}
            placeholder="One action per line"
          />
        </div>

        <div ref={analysisRef}>
          {analysis?.decision && (
            <div className="strategy-card">
              <div className="strategy-head">
                <div>
                  <p className="panel-kicker">Deterministic output</p>
                  <h3>{analysis.decision.action.replaceAll('_', ' ')}</h3>
                </div>
                <span className={`metric-badge ${analysis.decision.validation.status}`}>{analysis.decision.validation.status}</span>
              </div>

              <div className="operator-card-grid">
                <article className="subcard">
                  <p className="subcard-title">Equity</p>
                  <div className="subcard-metric">{formatPercent(analysis.decision.equity)}</div>
                  <p className="subcard-copy">
                    Pot odds {analysis.decision.pot_odds !== null && analysis.decision.pot_odds !== undefined ? formatPercent(analysis.decision.pot_odds) : 'n/a'}
                  </p>
                </article>
                <article className="subcard">
                  <p className="subcard-title">Frequency</p>
                  <div className="subcard-metric">{formatPercent(analysis.decision.frequency)}</div>
                  <p className="subcard-copy">Strength: {analysis.decision.hand_strength}</p>
                </article>
                <article className="subcard">
                  <p className="subcard-title">Sizing</p>
                  <div className="subcard-metric">
                    {analysis.decision.sizing_fraction
                      ? `${Math.round(analysis.decision.sizing_fraction * 100)}% pot`
                      : analysis.decision.sizing_bb
                        ? `${analysis.decision.sizing_bb.toFixed(1)}bb`
                        : 'n/a'}
                  </div>
                  <p className="subcard-copy">{analysis.spot.street || analysis.decision.street}</p>
                </article>
              </div>

              <div className="list-block">
                <h3>Reasoning</h3>
                <p>{analysis.decision.reasoning}</p>
                {analysis.decision.barrel_plan && <p className="subcard-copy">Plan: {analysis.decision.barrel_plan}</p>}
                {analysis.decision.exploit_note && <p className="subcard-copy">Exploit: {analysis.decision.exploit_note}</p>}
              </div>

              <div className="list-block">
                <h3>Validation warnings</h3>
                {analysis.decision.validation.warnings.length ? (
                  <ul>
                    {analysis.decision.validation.warnings.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p>No active warnings.</p>
                )}
              </div>

              {analysis.review && (
                <div className="list-block">
                  <h3>Replay review</h3>
                  <p>{analysis.review.summary}</p>
                  <p className="subcard-copy">Agreement: {analysis.review.agreement}</p>
                  {analysis.review.solver_line && (
                    <p className="subcard-copy">
                      Solver-lite: {analysis.review.solver_line.action} at {Math.round(analysis.review.solver_line.frequency * 100)}%
                      {analysis.review.solver_line.sizing ? ` • ${Math.round(analysis.review.solver_line.sizing * 100)}% pot` : ''}
                    </p>
                  )}
                  <ul>
                    {analysis.review.review_focus.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="bookmark-row">
                <input
                  className="input"
                  placeholder="Add a note..."
                  value={uiState.bookmarkNote}
                  onChange={(event) => setUiState((current) => ({ ...current, bookmarkNote: event.target.value }))}
                />
                <button className="btn" onClick={bookmarkSpot} disabled={loading || screenshotLoading}>
                  Mark for review
                </button>
              </div>
            </div>
          )}
        </div>

        {error && <p className="operator-error">{error}</p>}
      </section>

      <section className="panel card">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Study queue</p>
            <h2 className="panel-title">Marked Hands</h2>
          </div>
        </div>

        <div className="queue-list">
          {queue.length ? (
            queue.map((item) => (
              <article className={`queue-item ${selectedReviewId === item.id ? 'active' : ''}`} key={item.id}>
                <button className="queue-open" onClick={() => loadReviewItem(item.id)}>
                  <span className="queue-title">{item.label}</span>
                  <span className="queue-meta">{formatTime(item.created_at)}</span>
                  {item.note && <span className="queue-note">{item.note}</span>}
                </button>
                <button
                  className="ghost-btn"
                  style={{ position: 'relative', minWidth: 64, textAlign: 'center' }}
                  disabled={removingId === item.id}
                  onClick={() => removeQueueItem(item.id)}
                >
                  {removingId === item.id ? '...' : 'remove'}
                </button>
              </article>
            ))
          ) : (
            <p className="subcard-copy">No marked hands yet.</p>
          )}
        </div>

        {selectedReview && (
          <div className="strategy-card compact">
            <div className="strategy-head">
              <div>
                <p className="panel-kicker">Replay packet</p>
                <h3>{selectedReview.item.label}</h3>
              </div>
              <button className="ghost-btn" onClick={replaySelected}>load to form</button>
            </div>

            <div className="list-block">
              <h3>Saved spot</h3>
              <p>{selectedReview.item.spot.hole_cards} on {selectedReview.item.spot.board || 'preflop'} from {selectedReview.item.spot.position}</p>
              <p className="subcard-copy">{(selectedReview.item.spot.action_history || []).join(' → ') || 'No action history saved'}</p>
            </div>

            <div className="list-block">
              <h3>Review focus</h3>
              <p>{selectedReview.review.summary}</p>
              <ul>
                {(selectedReview.review.review_focus || []).map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>

            {selectedReview.review.solver_line && (
              <div className="operator-card-grid">
                <article className="subcard">
                  <p className="subcard-title">Board texture</p>
                  <div className="subcard-metric">{selectedReview.review.board_texture}</div>
                  <p className="subcard-copy">{selectedReview.review.board_description}</p>
                </article>
                <article className="subcard">
                  <p className="subcard-title">Solver-lite</p>
                  <div className="subcard-metric">{selectedReview.review.solver_line.action}</div>
                  <p className="subcard-copy">{Math.round(selectedReview.review.solver_line.frequency * 100)}% frequency</p>
                </article>
                <article className="subcard">
                  <p className="subcard-title">Agreement</p>
                  <div className="subcard-metric">{selectedReview.review.agreement}</div>
                  <p className="subcard-copy">{selectedReview.review.hand_classification}</p>
                </article>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
