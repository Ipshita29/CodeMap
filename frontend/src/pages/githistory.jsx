import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'

import {
  analyzeChangeImpact,
  ApiError,
  fetchAreaImpact,
  fetchCommitDiff,
  fetchEvolutionTimeline,
  fetchGitSummary,
  fetchRepositoryHealth,
} from '@/api'
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

function formatPeriod(start, end) {
  const startLabel = formatDate(start)
  const endLabel = formatDate(end)
  return startLabel === endLabel ? startLabel : `${startLabel} – ${endLabel}`
}

function areaSlug(area) {
  return area.toLowerCase().replace(/\s+/g, '-')
}

function evolutionQuestion(area) {
  const fileList = area.files.slice(0, 15).join(', ')
  const commitMessages = area.commits
    .slice(0, 10)
    .map((c) => `"${c.message}"`)
    .join(', ')
  return (
    `Between ${formatDate(area.period_start)} and ${formatDate(area.period_end)}, ${area.commit_count} ` +
    `commit${area.commit_count === 1 ? '' : 's'} classified as ${area.area} changed these files: ${fileList}. ` +
    `The commit messages were: ${commitMessages}. Explain what work happened in this period and why it matters, ` +
    `using only the files and commits named here plus what you can see in the actual source.`
  )
}

// =====================================================================
// Evolution Timeline -- Git's real commits, deterministically classified
// and grouped into areas (see backend/evolution.py). No AI involved in
// computing any of this; "Explain this period" hands the already-computed
// evidence to the existing Ask CodeMap chat instead of a separate AI path.
// =====================================================================

function CommitDiff({ repositoryId, hash, path }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ['commit-diff', repositoryId, hash, path],
    queryFn: () => fetchCommitDiff(repositoryId, hash, path),
    retry: false,
  })

  if (isPending) return <p className="card-subtitle evolution-diff-note">Loading diff…</p>
  if (isError || !data?.has_diff) return <p className="card-subtitle evolution-diff-note">No diff available.</p>

  return (
    <pre className="evolution-diff">
      {data.diff.split('\n').map((line, index) => {
        let lineClass = 'evolution-diff-line'
        if (line.startsWith('+') && !line.startsWith('+++')) lineClass += ' evolution-diff-line-add'
        else if (line.startsWith('-') && !line.startsWith('---')) lineClass += ' evolution-diff-line-del'
        else if (line.startsWith('@@')) lineClass += ' evolution-diff-line-hunk'
        return (
          <span key={index} className={lineClass}>
            {line}
            {'\n'}
          </span>
        )
      })}
    </pre>
  )
}

function CommitEvidenceRow({ repositoryId, commit }) {
  const [expandedFile, setExpandedFile] = useState(null)

  return (
    <li className="evolution-commit-row">
      <div className="evolution-commit-main">
        <span className="commit-hash">{commit.short_hash}</span>
        <p className="evolution-commit-message">{commit.message}</p>
        <p className="timeline-meta">
          {commit.author} · {formatDate(commit.date)} · +{commit.additions} / -{commit.deletions}
          {commit.area === 'Multi-area' && (
            <>
              {' '}
              ·{' '}
              {Object.entries(commit.area_breakdown)
                .map(([area, count]) => `${area} (${count})`)
                .join(', ')}
            </>
          )}
        </p>
      </div>
      {commit.files.length > 0 && (
        <ul className="evolution-commit-files">
          {commit.files.map((path) => (
            <li key={path}>
              <button
                type="button"
                className="link-button evolution-file-toggle"
                onClick={() => setExpandedFile(expandedFile === path ? null : path)}
              >
                {expandedFile === path ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                <span className="hotspot-path">{path}</span>
              </button>
              {expandedFile === path && <CommitDiff repositoryId={repositoryId} hash={commit.hash} path={path} />}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

// Change Impact for one Evolution Area -- fetched only once the area is
// opened (queries are enabled: expanded), and entirely backend-computed
// from real Git diffs + the repository's dependency graph (see
// backend/evolution.py's compute_area_impact). "Explain this impact" hands
// the already-computed facts to the existing Ask CodeMap chat, same as
// every other AI-explain button on this page -- no separate AI scoring.
function AreaImpactPanel({ repositoryId, areaId, onAskAbout }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['area-impact', repositoryId, areaId],
    queryFn: () => fetchAreaImpact(repositoryId, areaId),
    retry: false,
  })

  if (isPending) {
    return <p className="card-subtitle">Calculating impact from Git history and the dependency graph…</p>
  }
  if (isError) {
    return <p className="card-subtitle">{errorMessage(error)}</p>
  }
  if (!data) return null

  return (
    <div className="area-impact">
      <div className="area-impact-header">
        <span className={`risk-badge risk-${data.level}`}>
          {data.level.toUpperCase()} · {data.score}
        </span>
        <p className="area-impact-headline">{data.headline}</p>
      </div>

      <ul className="area-impact-reasons">
        {data.reasons.map((reason, index) => (
          <li key={index}>{reason}</li>
        ))}
      </ul>

      <p className="git-stat-note">{data.calibration_note}</p>

      <button
        type="button"
        className="link-button mt-3"
        onClick={() =>
          onAskAbout(
            `${data.headline} ${data.reasons.join(' ')} Explain in plain terms what this means for someone ` +
              `about to review or build on this change, using only the facts above.`,
          )
        }
      >
        Explain this impact
      </button>

      {(data.file_connectivity.length > 0 || data.import_changes.files_scanned > 0) && (
        <div className="area-impact-relationships">
          <h4 className="evolution-evidence-heading">Dependency relationships touched</h4>
          {data.file_connectivity.length > 0 ? (
            <ul className="impact-connectivity-list">
              {data.file_connectivity.map((file) => (
                <li key={file.path}>
                  <span className="hotspot-path">{file.path}</span>
                  <span className="timeline-meta">
                    {file.fan_in} dependent{file.fan_in === 1 ? '' : 's'} · {file.fan_out} dependenc
                    {file.fan_out === 1 ? 'y' : 'ies'}
                    {file.functions + file.classes > 0
                      ? ` · ${file.functions} function(s), ${file.classes} class(es)`
                      : ''}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="card-subtitle">No files in this area appear in the current dependency graph.</p>
          )}
          {data.import_changes.files_scanned > 0 && (
            <p className="git-stat-note">
              {data.import_changes.added} import statement{data.import_changes.added === 1 ? '' : 's'} added,{' '}
              {data.import_changes.removed} removed, across {data.import_changes.files_scanned} scanned diff
              {data.import_changes.files_scanned === 1 ? '' : 's'}
              {data.import_changes.truncated ? ' (bounded sample)' : ''}.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function EvolutionAreaCard({ repositoryId, area, onAskAbout }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <article className="evolution-area-card">
      <button type="button" className="evolution-area-header" onClick={() => setExpanded((prev) => !prev)}>
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span className={`evolution-area-badge evolution-area-badge-${areaSlug(area.area)}`}>{area.area}</span>
        <span className="evolution-area-period">{formatPeriod(area.period_start, area.period_end)}</span>
        <span className="evolution-area-stats">
          {area.commit_count} commit{area.commit_count === 1 ? '' : 's'} · {area.files.length}
          {area.files_truncated ? '+' : ''} file{area.files.length === 1 && !area.files_truncated ? '' : 's'} ·{' '}
          <span className="evolution-additions">+{area.additions}</span>{' '}
          <span className="evolution-deletions">-{area.deletions}</span>
        </span>
      </button>

      {area.modules.length > 0 && (
        <div className="evolution-modules">
          {area.modules.map((module) => (
            <span key={module} className="evolution-module-chip">
              {module}
            </span>
          ))}
        </div>
      )}

      <button type="button" className="link-button mt-3" onClick={() => onAskAbout(evolutionQuestion(area))}>
        Explain this period
      </button>

      {expanded && (
        <div className="evolution-evidence evolution-evidence-sections">
          <div>
            <h3 className="evolution-evidence-heading">Change Impact</h3>
            <AreaImpactPanel repositoryId={repositoryId} areaId={area.id} onAskAbout={onAskAbout} />
          </div>

          <div>
            <h3 className="evolution-evidence-heading">Evidence: commits &amp; files</h3>
            <ul className="evolution-commit-list">
              {area.commits.map((commit) => (
                <CommitEvidenceRow key={commit.hash} repositoryId={repositoryId} commit={commit} />
              ))}
            </ul>
          </div>
        </div>
      )}
    </article>
  )
}

function EvolutionTimelineSection({ repositoryId, onAskAbout }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['evolution-timeline'],
    queryFn: () => fetchEvolutionTimeline(repositoryId),
    retry: false,
  })

  return (
    <section className="overview-block">
      <h2>Evolution Timeline</h2>

      {isPending && <p className="card-subtitle">Reading Git history and classifying commits…</p>}
      {isError && <p className="card-subtitle">{errorMessage(error)}</p>}
      {data && !data.has_git_history && <p className="card-subtitle">No Git history available.</p>}

      {data?.has_git_history && (
        <>
          <p className="git-stat-note">
            {data.analyzed_commit_count} commit{data.analyzed_commit_count === 1 ? '' : 's'} analyzed
            {data.truncated ? ' (most recent window)' : ''}, grouped into {data.areas.length} evolution area
            {data.areas.length === 1 ? '' : 's'} by file path, extension, and directory — deterministically, not by
            AI. Expand a period for the underlying commits and files; use "Explain this period" to have Ask CodeMap
            walk through it.
          </p>

          {data.areas.length > 0 ? (
            <div className="evolution-timeline">
              {data.areas.map((area) => (
                <EvolutionAreaCard key={area.id} repositoryId={repositoryId} area={area} onAskAbout={onAskAbout} />
              ))}
            </div>
          ) : (
            <p className="card-subtitle">No commits found.</p>
          )}
        </>
      )}
    </section>
  )
}

// =====================================================================
// Change Impact -- the same structurally-verified impact analysis
// Architecture's Impact mode uses (backend/analyzer.py's ImpactAnalyzer),
// reused here without its graph view: pick a file (a hotspot suggestion or
// any path) and see its real dependents, related routes, and risk score.
// =====================================================================

function ChangeImpactSection({ repositoryId, suggestedFiles, onAskAbout }) {
  const [file, setFile] = useState('')
  const impact = useMutation({ mutationFn: (path) => analyzeChangeImpact(repositoryId, { file: path }) })

  function handleAnalyze(path) {
    const target = (path ?? file).trim()
    if (!target) return
    setFile(target)
    impact.mutate(target)
  }

  return (
    <section className="overview-block">
      <h2>Change Impact</h2>
      <p className="card-subtitle">
        Pick a file to see what actually depends on it — structurally verified from the real import graph, not
        guessed.
      </p>

      {suggestedFiles.length > 0 && (
        <div className="impact-suggestions">
          {suggestedFiles.map((path) => (
            <button key={path} type="button" className="mode-btn" onClick={() => handleAnalyze(path)}>
              {path}
            </button>
          ))}
        </div>
      )}

      <div className="impact-input-row">
        <input
          className="input"
          value={file}
          onChange={(event) => setFile(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && handleAnalyze()}
          placeholder="path/to/file.js"
        />
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => handleAnalyze()}
          disabled={impact.isPending || !file.trim()}
        >
          {impact.isPending ? 'Analyzing…' : 'Analyze Impact'}
        </button>
      </div>

      {impact.data && (
        <div className="panel impact-report mt-6">
          <div className="impact-report-header">
            <h3 className="panel-title">Impact of changing {impact.data.file}</h3>
            <span className={`risk-badge risk-${impact.data.risk.level}`}>
              {impact.data.risk.level.toUpperCase()} · {impact.data.risk.score}
            </span>
          </div>
          <p className="card-subtitle">
            {impact.data.direct_dependents.length} direct dependent(s), {impact.data.indirect_dependents.length}{' '}
            indirect dependent(s)
            {impact.data.related_routes.length > 0 ? `, ${impact.data.related_routes.length} related route(s)` : ''}
            {impact.data.related_files.length > 0
              ? `, ${impact.data.related_files.length} related frontend file(s)`
              : ''}
            .
          </p>
          {impact.data.summary ? (
            <p className="summary-text">{impact.data.summary}</p>
          ) : (
            <p className="card-subtitle">AI explanation unavailable (no AI provider configured for this backend).</p>
          )}
          <button
            type="button"
            className="link-button mt-3"
            onClick={() => onAskAbout(`What could break if I change ${impact.data.file}?`)}
          >
            Ask about this
          </button>
        </div>
      )}
      {impact.isError && <p className="card-subtitle mt-3">{errorMessage(impact.error)}</p>}
    </section>
  )
}

// =====================================================================
// Hotspots & Architecture Drift -- most-modified files (Git activity) next
// to structural drift signals (import cycles, high coupling) already
// computed by analyzer.py's HealthAnalyzer -- the same data GET
// /repository/health feeds Health's own score, just filtered to the
// "architecture" category and shown here in Git History context.
// =====================================================================

function HotspotsAndDriftSection({ hotspots, health, onAskAbout }) {
  const architectureFindings = (health.data?.findings ?? []).filter((finding) => finding.category === 'architecture')

  return (
    <section className="overview-block">
      <h2>Hotspots &amp; Architecture Drift</h2>
      <div className="overview-grid">
        <div>
          <h3 className="git-subsection-title">Most changed files</h3>
          {hotspots.length > 0 ? (
            <ul className="hotspot-list">
              {hotspots.map((file) => (
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
        </div>

        <div>
          <h3 className="git-subsection-title">Architecture drift signals</h3>
          {health.isPending && <p className="card-subtitle">Checking for structural drift…</p>}
          {health.isError && <p className="card-subtitle">{errorMessage(health.error)}</p>}
          {health.data &&
            (architectureFindings.length > 0 ? (
              <ul className="finding-list">
                {architectureFindings.map((finding, index) => (
                  <li key={index} className={`finding-item finding-item-${finding.severity}`}>
                    <div className="finding-header">
                      <span className={`finding-severity finding-severity-${finding.severity}`}>
                        {finding.severity}
                      </span>
                      {finding.path && <span className="finding-path">{finding.path}</span>}
                    </div>
                    <p className="finding-reason">{finding.reason}</p>
                    <p className="finding-recommendation">{finding.recommendation}</p>
                    <button
                      type="button"
                      className="link-button mt-3"
                      onClick={() =>
                        onAskAbout(
                          `Explain this architecture drift finding and how to address it: "${finding.reason}"${finding.path ? ` (${finding.path})` : ''}.`,
                        )
                      }
                    >
                      Ask about this
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="card-subtitle">No structural drift detected (import cycles, unusually high coupling).</p>
            ))}
        </div>
      </div>
    </section>
  )
}

export function GitHistory({ repositoryId, onAskAbout }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['git-summary'],
    queryFn: () => fetchGitSummary(repositoryId),
    retry: false,
  })
  // Shares the exact ['repository-health'] cache entry Health's own tab
  // reads -- visiting either tab first means the other never re-fetches.
  const health = useQuery({
    queryKey: ['repository-health'],
    queryFn: () => fetchRepositoryHealth(repositoryId),
    retry: false,
  })

  const hotspotFiles = data?.activity?.most_modified_files ?? []

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

          <EvolutionTimelineSection repositoryId={repositoryId} onAskAbout={onAskAbout} />
          <ChangeImpactSection
            repositoryId={repositoryId}
            suggestedFiles={hotspotFiles.slice(0, 6).map((file) => file.path)}
            onAskAbout={onAskAbout}
          />
          <HotspotsAndDriftSection hotspots={hotspotFiles} health={health} onAskAbout={onAskAbout} />
        </>
      )}
    </div>
  )
}
