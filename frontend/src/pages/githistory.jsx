import { useQuery } from '@tanstack/react-query'

import { ApiError, fetchGitSummary } from '@/api'
import '../css/githistory.css'

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

function formatDate(iso) {
  if (!iso) return 'unknown date'
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

export function GitHistory({ onAskAbout }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['git-summary'],
    queryFn: fetchGitSummary,
    retry: false,
  })

  return (
    <div className="architecture-workspace">
      <h1 className="subview-heading">Git History</h1>

      {isPending && (
        <div className="panel">
          <p className="card-subtitle">Reading Git history…</p>
        </div>
      )}

      {isError && (
        <div className="panel">
          <h2 className="panel-title">Could not load Git history</h2>
          <p className="card-subtitle">{errorMessage(error)}</p>
        </div>
      )}

      {data && !data.has_git_history && (
        <div className="panel">
          <h2 className="panel-title">No Git history available</h2>
          <p className="card-subtitle">This repository may not contain Git metadata.</p>
        </div>
      )}

      {data?.has_git_history && (
        <>
          {data.latest_commit && (
            <section className="overview-block" style={{ borderTop: 'none', paddingTop: 0 }}>
              <h2>Latest activity</h2>
              <p className="card-title">{data.latest_commit.message}</p>
              <p className="card-subtitle">
                {data.latest_commit.author} · {formatDate(data.latest_commit.date)}
              </p>
              <span className="commit-hash mt-3" style={{ display: 'inline-block' }}>
                {data.latest_commit.short_hash}
              </span>
            </section>
          )}

          <div className="metrics-row">
            <span>
              <strong>
                {data.activity.total_commits}
                {data.activity.truncated ? '+' : ''}
              </strong>{' '}
              commits
            </span>
            <span>
              <strong>{data.activity.contributors}</strong> contributors
            </span>
            <span>
              <strong>{data.activity.commits_last_7_days}</strong> last 7 days
            </span>
            <span>
              <strong>{data.activity.commits_last_30_days}</strong> last 30 days
            </span>
          </div>
          {data.activity.truncated && (
            <p className="git-stat-note">
              Statistics are based on the most recently analyzed {data.activity.analyzed_commit_count} commits.
            </p>
          )}

          <div className="overview-grid">
            <section className="overview-block">
              <h2>Commit Timeline</h2>
              {data.timeline.length > 0 ? (
                <ul className="timeline">
                  {data.timeline.map((commit) => (
                    <li key={commit.hash} className="timeline-item">
                      <p className="timeline-date">{formatDate(commit.date)}</p>
                      <p className="timeline-message">{commit.message}</p>
                      <p className="timeline-meta">
                        {commit.author} · <span className="commit-hash">{commit.short_hash}</span> ·{' '}
                        {commit.files_changed} file{commit.files_changed === 1 ? '' : 's'}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="card-subtitle">No commits found.</p>
              )}
            </section>

            <section className="overview-block">
              <h2>Most Changed Files</h2>
              {data.activity.most_modified_files.length > 0 ? (
                <ul className="hotspot-list">
                  {data.activity.most_modified_files.map((file) => (
                    <li key={file.path} className="hotspot-row">
                      <span className="hotspot-path">{file.path}</span>
                      <span className="hotspot-row-actions">
                        <span className="hotspot-count">{file.commit_count} commits</span>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() =>
                            onAskAbout(
                              `Why has ${file.path} changed so frequently (${file.commit_count} commits), and what should I know about it?`,
                            )
                          }
                        >
                          Investigate
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="card-subtitle">No file history available.</p>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
