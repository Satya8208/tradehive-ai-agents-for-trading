// Stats panel component for displaying generation statistics

function StatCard({ label, value, subValue, icon, color }) {
  return (
    <div className="bg-[var(--bg-secondary)] rounded-xl p-4 text-center transition-all hover:scale-[1.02]">
      <div className="text-2xl mb-1">{icon}</div>
      <div
        className="text-2xl font-bold mb-0.5"
        style={{ color: color || 'var(--text-primary)' }}
      >
        {value}
      </div>
      {subValue && (
        <div className="text-xs text-[var(--text-muted)] mb-1">
          {subValue}
        </div>
      )}
      <div className="text-xs text-[var(--text-secondary)] font-medium uppercase tracking-wide">
        {label}
      </div>
    </div>
  )
}

function TechniqueBar({ name, count, percentage, color }) {
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs mb-1">
        <span className="text-[var(--text-secondary)] truncate max-w-[70%]">{name}</span>
        <span className="text-[var(--text-muted)]">{count}</span>
      </div>
      <div className="w-full h-1.5 bg-[var(--bg-primary)] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${percentage}%`, background: color || 'var(--accent)' }}
        />
      </div>
    </div>
  )
}

export default function StatsPanel({ stats, techniques }) {
  // Default stats if not provided
  const {
    total_generated = 0,
    approved_count = 0,
    duplicate_count = 0,
    rejected_count = 0,
    avg_novelty = 0,
    session_start = null,
    generations_this_session = 0
  } = stats || {}

  // Calculate percentages
  const approvedPct = total_generated > 0 ? ((approved_count / total_generated) * 100).toFixed(1) : 0
  const duplicatePct = total_generated > 0 ? ((duplicate_count / total_generated) * 100).toFixed(1) : 0
  const rejectedPct = total_generated > 0 ? ((rejected_count / total_generated) * 100).toFixed(1) : 0

  // Top techniques (sorted by count)
  const topTechniques = techniques
    ? Object.entries(techniques)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
    : []

  const maxTechniqueCount = topTechniques.length > 0 ? topTechniques[0][1] : 1

  // Session duration
  const sessionDuration = session_start
    ? formatDuration(new Date() - new Date(session_start))
    : '--'

  return (
    <div className="card p-4 mb-6">
      <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
        <span>📈</span>
        <span>Statistics</span>
      </h2>

      {/* Main stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <StatCard
          label="Total"
          value={total_generated}
          icon="📊"
          color="var(--text-primary)"
        />
        <StatCard
          label="Approved"
          value={approved_count}
          subValue={`${approvedPct}%`}
          icon="✅"
          color="#22c55e"
        />
        <StatCard
          label="Duplicates"
          value={duplicate_count}
          subValue={`${duplicatePct}%`}
          icon="⚠️"
          color="#eab308"
        />
        <StatCard
          label="Rejected"
          value={rejected_count}
          subValue={`${rejectedPct}%`}
          icon="❌"
          color="#ef4444"
        />
        <StatCard
          label="Avg Novelty"
          value={`${Math.round(avg_novelty * 100)}%`}
          icon="✨"
          color="#3b82f6"
        />
      </div>

      {/* Session info */}
      <div className="flex items-center justify-between mb-4 py-2 px-3 bg-[var(--bg-secondary)] rounded-lg">
        <div className="flex items-center gap-4 text-sm">
          <div>
            <span className="text-[var(--text-muted)]">Session: </span>
            <span className="font-medium">{sessionDuration}</span>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">This session: </span>
            <span className="font-medium">{generations_this_session} strategies</span>
          </div>
        </div>
      </div>

      {/* Top techniques */}
      {topTechniques.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-secondary)] mb-3">
            Top Techniques
          </h3>
          {topTechniques.map(([name, count], index) => (
            <TechniqueBar
              key={name}
              name={name}
              count={count}
              percentage={(count / maxTechniqueCount) * 100}
              color={getTechniqueColor(index)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// Helper to format duration
function formatDuration(ms) {
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m`
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`
  }
  return `${seconds}s`
}

// Get color for technique bar
function getTechniqueColor(index) {
  const colors = ['#f97316', '#3b82f6', '#22c55e', '#8b5cf6', '#eab308']
  return colors[index % colors.length]
}
