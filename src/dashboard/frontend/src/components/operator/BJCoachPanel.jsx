import { useEffect, useState, useRef } from 'react'

const STORAGE_KEY = 'tradehive-operator-bj'

const DEFAULT_CUSTOM_PROFILE = {
  name: 'my_custom_room',
  num_decks: 6,
  penetration: 0.75,
  dealer_hits_soft_17: false,
  blackjack_pays: 1.5,
  late_surrender: true,
  double_after_split: true,
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw
      ? JSON.parse(raw)
      : {
          countingSystem: 'hi_lo',
          selectedProfile: 'live_75pen',
          customProfile: DEFAULT_CUSTOM_PROFILE,
          reviewForm: {
            hands: 100,
            hours: 1.5,
            wagered: 1500,
            pnl: 120,
            min_bet: 25,
            max_bet: 150,
          },
        }
  } catch {
    return {
      countingSystem: 'hi_lo',
      selectedProfile: 'live_75pen',
      customProfile: DEFAULT_CUSTOM_PROFILE,
      reviewForm: { hands: 100, hours: 1.5, wagered: 1500, pnl: 120, min_bet: 25, max_bet: 150 },
    }
  }
}

// #15 — consistent badge mapping
function badgeClass(status) {
  if (!status) return 'neutral'
  const s = String(status).toLowerCase()
  if (['pass', 'validated', 'certified', 'approved', 'live approved'].includes(s)) return 'validated'
  if (['provisional', 'near_ready', 'near ready', 'warning'].includes(s)) return 'provisional'
  if (['fail', 'unvalidated', 'hold', 'in_training', 'in training'].includes(s)) return 'unvalidated'
  return 'neutral'
}

// Humanise backend keys
function humanize(str) {
  if (!str) return ''
  const MAP = {
    hi_lo: 'Hi-Lo',
    omega_ii: 'Omega II',
    wong_halves: 'Wong Halves',
    live_75pen: 'Live 75% Pen',
    coin_casino: 'Coin Casino',
    evo_live: 'Evolution Live',
    pragma_live: 'Pragmatic Live',
    evo_infinite: 'Evolution Infinite',
    full_table_counting: 'Full-table counting',
    bet_sizing: 'Bet sizing',
    deviation: 'Deviations',
    table_ready: 'Table Ready',
    foundation: 'Foundation',
    developing: 'Developing',
    advanced: 'Advanced',
    spread: 'Spread',
    spread_aggressive: 'Spread Aggressive',
    kelly: 'Kelly',
  }
  if (MAP[str]) return MAP[str]
  return str.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

const LEVEL_DESCRIPTIONS = {
  foundation: 'No drills completed yet. Start training.',
  developing: 'Some accuracy but below certification thresholds.',
  advanced: 'Strong accuracy. Close to live certification.',
  table_ready: 'All certification checks passed. Cleared for live play.',
}

function metricTone(value) {
  if (value >= 90) return 'validated'
  if (value >= 75) return 'provisional'
  return 'unvalidated'
}

export default function BJCoachPanel({ apiBase }) {
  const [uiState, setUiState] = useState(loadState)
  const [summary, setSummary] = useState(null)
  const [profiles, setProfiles] = useState([])
  const [plan, setPlan] = useState(null)
  const [review, setReview] = useState(null)
  const [loadingPlan, setLoadingPlan] = useState(false)
  const [loadingReview, setLoadingReview] = useState(false)
  const [reviewTimestamp, setReviewTimestamp] = useState(null)
  const [error, setError] = useState(null)
  const reviewRef = useRef(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(uiState))
  }, [uiState])

  useEffect(() => {
    const load = async () => {
      try {
        const [summaryRes, profilesRes] = await Promise.all([
          fetch(`${apiBase}/api/blackjack/coach-summary?counting_system=${uiState.countingSystem}`),
          fetch(`${apiBase}/api/blackjack/profiles`),
        ])
        const summaryData = await summaryRes.json()
        const profilesData = await profilesRes.json()
        if (!summaryRes.ok) throw new Error(summaryData.detail || 'Failed to load coach summary')
        if (!profilesRes.ok) throw new Error(profilesData.detail || 'Failed to load profiles')
        setSummary(summaryData)
        setProfiles(profilesData)
      } catch (fetchError) {
        setError(fetchError.message)
      }
    }
    load()
  }, [apiBase, uiState.countingSystem])

  const updateReviewField = (field, value) => {
    setUiState((current) => ({
      ...current,
      reviewForm: { ...current.reviewForm, [field]: value },
    }))
  }

  const updateCustomProfile = (field, value) => {
    setUiState((current) => ({
      ...current,
      customProfile: { ...current.customProfile, [field]: value },
    }))
  }

  const generatePlan = async () => {
    setLoadingPlan(true)
    setError(null)
    try {
      const payload = {
        counting_system: uiState.countingSystem,
        profile_name: uiState.selectedProfile === '__custom__' ? null : uiState.selectedProfile,
        custom_profile: uiState.selectedProfile === '__custom__' ? uiState.customProfile : null,
      }
      const response = await fetch(`${apiBase}/api/blackjack/session-plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Failed to build session plan')
      setPlan(data)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoadingPlan(false)
    }
  }

  // #10 — loading state + timestamp on review
  const reviewSession = async () => {
    setLoadingReview(true)
    setError(null)
    try {
      const response = await fetch(`${apiBase}/api/blackjack/review-session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          counting_system: uiState.countingSystem,
          ...Object.fromEntries(
            Object.entries(uiState.reviewForm).map(([key, value]) => [key, Number(value)])
          ),
        }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Failed to review session')
      setReview(data)
      setReviewTimestamp(new Date())
      // #6 style — scroll to results
      setTimeout(() => reviewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoadingReview(false)
    }
  }

  return (
    <div className="operator-section-grid">
      <section className="panel card">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Readiness</p>
            <h2 className="panel-title">BJ Coach</h2>
          </div>
          <select
            className="input operator-select"
            value={uiState.countingSystem}
            onChange={(event) =>
              setUiState((current) => ({ ...current, countingSystem: event.target.value }))
            }
          >
            <option value="hi_lo">Hi-Lo</option>
            <option value="omega_ii">Omega II</option>
            <option value="wong_halves">Wong Halves</option>
          </select>
        </div>

        {summary && (
          <>
            {/* #14 — level with tooltip/description */}
            <div className="coach-score">
              <div className={`metric-badge ${metricTone(summary.score)}`} title={LEVEL_DESCRIPTIONS[summary.level] || ''}>
                Stage: {humanize(summary.level)}
              </div>
              <strong>{summary.score}</strong>
              <span>readiness score</span>
            </div>

            <div className="strategy-card compact">
              <div className="strategy-head">
                <div>
                  <p className="panel-kicker">Certification gate</p>
                  <h3>{humanize(summary.certification.status)}</h3>
                </div>
                <span className={`metric-badge ${badgeClass(summary.certification.ready_for_live_play ? 'validated' : 'hold')}`}>
                  {summary.certification.ready_for_live_play ? 'live approved' : 'hold'}
                </span>
              </div>

              {/* #8 — FAIL badges with drill name as CTA hint */}
              <div className="queue-list">
                {summary.certification.checks.map((check) => (
                  <article className="queue-item static" key={check.drill}>
                    <div>
                      <p className="queue-title">{check.label}</p>
                      <p className="queue-meta">
                        {check.recent_pct}% accuracy over {check.sessions} session{check.sessions === 1 ? '' : 's'}
                        {check.target_time_sec ? ` \u2022 ${check.recent_avg_time_sec ?? 'n/a'}s vs ${check.target_time_sec}s` : ''}
                      </p>
                      {!check.passed && (
                        <p className="subcard-copy" style={{ marginTop: 4 }}>
                          Run: <code style={{ color: 'var(--gold)', fontSize: '0.75rem' }}>python -m src.agents.blackjack.pro_trainer</code>
                        </p>
                      )}
                    </div>
                    <span className={`metric-badge ${badgeClass(check.passed ? 'pass' : 'fail')}`}>
                      {check.passed ? 'pass' : 'fail'}
                    </span>
                  </article>
                ))}
              </div>
            </div>

            <div className="operator-card-grid">
              {Object.entries(summary.summary.drills || {}).map(([name, drill]) => (
                <article className="subcard" key={name}>
                  <p className="subcard-title">{humanize(name)}</p>
                  <div className="subcard-metric">{drill.recent_pct}%</div>
                  <p className="subcard-copy">
                    Recent {drill.sessions} sessions
                    {drill.recent_avg_time_sec ? ` \u2022 ${drill.recent_avg_time_sec}s avg` : ''}
                  </p>
                </article>
              ))}
            </div>

            {/* #1 — blockers rendered properly with humanized names */}
            <div className="list-block">
              <h3>Current blockers</h3>
              {summary.blockers.length ? (
                <ul>
                  {summary.blockers.map((item, i) => (
                    <li key={i}>{humanize(item)}</li>
                  ))}
                </ul>
              ) : (
                <p>No active blockers. This system considers you table-ready on current evidence.</p>
              )}
            </div>

            {/* #1 + #7 — practice blocks always rendered, styled as actionable items */}
            <div className="list-block">
              <h3>Next practice blocks</h3>
              {summary.practice_blocks && summary.practice_blocks.length > 0 ? (
                <ul>
                  {summary.practice_blocks.map((item) => (
                    <li key={item.drill}>{item.prescription}</li>
                  ))}
                </ul>
              ) : (
                <p>Complete your first drill sessions to unlock practice recommendations.</p>
              )}
            </div>
          </>
        )}
      </section>

      {/* PLAN BUILDER */}
      <section className="panel card">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Session prep</p>
            <h2 className="panel-title">Plan Builder</h2>
          </div>
          <button className="btn" onClick={generatePlan} disabled={loadingPlan}>
            {loadingPlan ? 'Building\u2026' : 'Generate Plan'}
          </button>
        </div>

        <div className="field-grid two">
          <div>
            <label className="field-label">Profile</label>
            <select
              className="input operator-select"
              value={uiState.selectedProfile}
              onChange={(event) =>
                setUiState((current) => ({ ...current, selectedProfile: event.target.value }))
              }
            >
              {profiles.map((profile) => (
                <option key={profile.name} value={profile.name}>
                  {humanize(profile.name)}
                </option>
              ))}
              <option value="__custom__">Custom</option>
            </select>
          </div>
        </div>

        {uiState.selectedProfile === '__custom__' && (
          <div className="field-grid three">
            <div>
              <label className="field-label">Name</label>
              <input className="input" value={uiState.customProfile.name} onChange={(event) => updateCustomProfile('name', event.target.value)} />
            </div>
            <div>
              <label className="field-label">Decks</label>
              <input className="input" type="number" value={uiState.customProfile.num_decks} onChange={(event) => updateCustomProfile('num_decks', Number(event.target.value))} />
            </div>
            <div>
              <label className="field-label">Penetration</label>
              <input className="input" type="number" step="0.01" value={uiState.customProfile.penetration} onChange={(event) => updateCustomProfile('penetration', Number(event.target.value))} />
            </div>
          </div>
        )}

        {/* #9 — empty state when no plan generated yet */}
        {!plan && !loadingPlan && (
          <div className="list-block" style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text-dim)' }}>
            <p>Select a casino profile and click <strong style={{ color: 'var(--gold)' }}>Generate Plan</strong> to build your session strategy card.</p>
          </div>
        )}

        {plan && (
          <div className="strategy-card">
            <div className="strategy-head">
              <div>
                <p className="panel-kicker">Strategy card</p>
                <h3>{humanize(plan.profile_name)}</h3>
              </div>
              <span className={`metric-badge ${badgeClass(plan.validation_status)}`}>{plan.validation_status}</span>
            </div>

            <div className="operator-card-grid">
              <article className="subcard">
                <p className="subcard-title">Count system</p>
                <div className="subcard-metric">{humanize(plan.counting_system)}</div>
                <p className="subcard-copy">Bet method: {humanize(plan.betting_method)}</p>
              </article>
              <article className="subcard">
                <p className="subcard-title">Spread</p>
                <div className="subcard-metric">{plan.spread_ratio.toFixed(1)}x</div>
                <p className="subcard-copy">Ramp starts at TC +{plan.bet_ramp_tc.toFixed(1)}</p>
              </article>
              <article className="subcard">
                <p className="subcard-title">Expected hourly</p>
                <div className="subcard-metric">${plan.expected_hourly_rate.toFixed(2)}</div>
                <p className="subcard-copy">Planning input, not guaranteed</p>
              </article>
            </div>

            <div className="list-block">
              <h3>Validation notes</h3>
              <ul>
                {plan.validation_notes.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>

            <div className="list-block">
              <h3>Operator gate</h3>
              <p>{plan.operator_note}</p>
              <p className="subcard-copy">
                Readiness gate: <span className={`metric-badge ${badgeClass(plan.readiness_gate)}`}>{plan.readiness_gate}</span>
              </p>
            </div>
          </div>
        )}
      </section>

      {/* SESSION REVIEW */}
      <section className="panel card full-span">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">After action</p>
            <h2 className="panel-title">Session Review</h2>
          </div>
          <button className="btn" onClick={reviewSession} disabled={loadingReview}>
            {loadingReview ? 'Reviewing\u2026' : 'Review Session'}
          </button>
        </div>

        <div className="field-grid three">
          {Object.entries(uiState.reviewForm).map(([field, value]) => (
            <div key={field}>
              <label className="field-label">{humanize(field)}</label>
              <input
                className="input"
                type="number"
                step="0.1"
                value={value}
                onChange={(event) => updateReviewField(field, event.target.value)}
              />
            </div>
          ))}
        </div>

        {/* #10 — review results with timestamp */}
        <div ref={reviewRef}>
          {review && (
            <>
              {reviewTimestamp && (
                <p className="subcard-copy" style={{ marginTop: 12, marginBottom: 4, textAlign: 'right' }}>
                  Reviewed {reviewTimestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </p>
              )}
              <div className="operator-card-grid">
                <article className="subcard">
                  <p className="subcard-title">Hourly</p>
                  <div className="subcard-metric">${review.metrics.hourly_rate}</div>
                  <p className="subcard-copy">{review.metrics.hands_per_hour} hands/hr</p>
                </article>
                <article className="subcard">
                  <p className="subcard-title">ROI</p>
                  <div className="subcard-metric">{review.metrics.roi_pct}%</div>
                  <p className="subcard-copy">Expected hourly ${review.benchmark.expected_hourly_rate}</p>
                </article>
                <article className="subcard">
                  <p className="subcard-title">Discipline</p>
                  <div className="subcard-metric">{review.discipline_score}</div>
                  <p className="subcard-copy">
                    <span className={`metric-badge ${badgeClass(review.validation_status)}`}>{review.validation_status}</span>
                  </p>
                </article>

                <div className="list-block">
                  <h3>Strengths</h3>
                  <ul>
                    {review.strengths.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div className="list-block">
                  <h3>Leaks</h3>
                  <ul>
                    {review.leaks.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div className="list-block">
                  <h3>Next drills</h3>
                  <ul>
                    {review.next_drills.map((item, i) => (
                      <li key={i}>{humanize(item)}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </>
          )}
        </div>

        {error && <p className="operator-error">{error}</p>}
      </section>
    </div>
  )
}
