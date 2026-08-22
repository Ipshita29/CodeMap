import { useQuery } from '@tanstack/react-query'

import { ApiError, fetchRepositoryHealth } from '@/api'

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

function healthLabel(score) {
  if (score >= 80) return 'Excellent'
  if (score >= 60) return 'Good'
  if (score >= 40) return 'Needs attention'
  return 'Critical'
}

export function HealthDashboard({ onAskAbout }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['repository-health'],
    queryFn: fetchRepositoryHealth,
    retry: false,
  })

  return (
    <div className="architecture-workspace">
      <h1 className="subview-heading">Health</h1>

      {isPending && (
        <div className="panel">
          <p className="card-subtitle">Analyzing repository health…</p>
        </div>
      )}

      {isError && (
        <div className="panel">
          <h2 className="panel-title">Could not analyze repository health</h2>
          <p className="card-subtitle">{errorMessage(error)}</p>
        </div>
      )}

      {data && (
        <>
          <section className="overview-block" style={{ borderTop: 'none', paddingTop: 0 }}>
            <div className="health-score-hero health-score-hero-lg">
              <div className="health-score-ring health-score-ring-lg">
                <span className="health-score-ring-value health-score-ring-value-lg">{data.score}</span>
                <span className="health-score-ring-label">/ 100</span>
              </div>
              <div>
                <p className="health-score-headline">{healthLabel(data.score)}</p>
                <div className="health-category-grid mt-3">
                  {Object.entries(data.categories).map(([category, categoryScore]) => (
                    <div key={category} className="health-category">
                      <span className="health-category-label">{category}</span>
                      <div className="health-category-bar-track">
                        <div className="health-category-bar-fill" style={{ width: `${categoryScore}%` }} />
                      </div>
                      <span className="health-category-value">{categoryScore}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <p className="git-stat-note mt-6">
              Heuristic structural estimate based on file size, test/README presence, import-graph shape, and
              declared dependencies — not a substitute for a linter or security scanner.
            </p>
          </section>

          <section className="overview-block">
            <h2>Top issues</h2>
            {data.findings.length > 0 ? (
              <ul className="finding-list">
                {data.findings.map((finding, index) => (
                  <li key={index} className={`finding-item finding-item-${finding.severity}`}>
                    <div className="finding-header">
                      <span className={`finding-severity finding-severity-${finding.severity}`}>{finding.severity}</span>
                      <span className="finding-category">{finding.category}</span>
                      {finding.path && <span className="finding-path">{finding.path}</span>}
                    </div>
                    <p className="finding-reason">{finding.reason}</p>
                    <p className="finding-recommendation">{finding.recommendation}</p>
                    <button
                      type="button"
                      className="link-button mt-3"
                      onClick={() =>
                        onAskAbout(
                          `Explain this health finding and how to address it: "${finding.reason}"${finding.path ? ` (${finding.path})` : ''}.`,
                        )
                      }
                    >
                      Ask about this
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="card-subtitle">No issues found by the heuristic checks.</p>
            )}
          </section>
        </>
      )}
    </div>
  )
}
