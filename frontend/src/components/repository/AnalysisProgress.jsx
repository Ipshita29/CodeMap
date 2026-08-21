import { CheckCircle2, Loader2 } from 'lucide-react'

// Only two stages are real: the import that got us here already succeeded,
// and the day-2 scan is what this screen is actually waiting on. Everything
// else (architecture graph, git history, health) is built lazily per-section
// once the user opens it -- this deliberately does not pretend those are
// "in progress" here, since they haven't started.
export function AnalysisProgress({ repositoryName, fileCount, indexed }) {
  const stages = [
    { done: true, label: 'Repository fetched' },
    { done: indexed, label: indexed && fileCount != null ? `${fileCount} files indexed` : 'Indexing files and structure…' },
  ]
  const doneCount = stages.filter((stage) => stage.done).length

  return (
    <div className="panel card-center analysis-progress">
      <p className="card-title">Analyzing {repositoryName ?? 'repository'}…</p>
      <ul className="progress-stage-list">
        {stages.map((stage) => (
          <li key={stage.label} className={`progress-stage${stage.done ? ' progress-stage-done' : ''}`}>
            <span className="progress-stage-icon">
              {stage.done ? <CheckCircle2 size={16} /> : <Loader2 className="spinner" size={16} />}
            </span>
            {stage.label}
          </li>
        ))}
      </ul>
      <div className="progress-bar-track">
        <div className="progress-bar-fill" style={{ width: `${(doneCount / stages.length) * 100}%` }} />
      </div>
      <p className="git-stat-note mt-6">
        Architecture, Git history, and health analysis run when you open each section.
      </p>
    </div>
  )
}
