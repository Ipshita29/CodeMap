import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Loader2 } from 'lucide-react'

import { fetchRepositoryAnalysis } from '@/api'
import '../css/analyzing.css'

// Only two stages are real: the import that got us here already succeeded,
// and the day-2 scan is what this screen is actually waiting on. Everything
// else (architecture graph, git history, health) is built lazily per-section
// once the user opens it -- this deliberately does not pretend those are
// "in progress" here, since they haven't started.
function AnalysisProgress({ repositoryName, fileCount, indexed }) {
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

export function AnalyzingPage({ repositoryName, onReady, onBack }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['repository-analysis'],
    queryFn: () => fetchRepositoryAnalysis(repositoryName),
  })

  useEffect(() => {
    if (data) onReady()
  }, [data, onReady])

  return (
    <div className="app-shell">
      <div className="app-glow" />
      <div className="app-content">
        <header className="app-header">
          <div className="logo-mark">C</div>
          <span className="logo-text">CodeMap</span>
        </header>
        <main className="app-main">
          {isError ? (
            <div className="panel">
              <h1 className="card-title">Repository could not be analyzed</h1>
              <p className="card-subtitle">{error.message}</p>
              <button className="btn btn-outline btn-block mt-6" onClick={onBack}>
                Back
              </button>
            </div>
          ) : (
            <AnalysisProgress repositoryName={repositoryName} fileCount={data?.total_files} indexed={!isPending} />
          )}
        </main>
      </div>
    </div>
  )
}
