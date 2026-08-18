import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { ApiError, fetchGitSummary, generateRepositorySummary } from '@/api'

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

function formatBytes(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function computeTopFolders(files) {
  const counts = new Map()
  for (const file of files) {
    const top = file.path.includes('/') ? file.path.split('/')[0] : '(root)'
    counts.set(top, (counts.get(top) ?? 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6)
}

// Every insight here is derived from data already on screen (or already
// cached from a section the user visited) -- never invented. Capped at 5.
function buildInsights(data, gitSummary, healthCache) {
  const insights = []
  const { languages, frameworks, statistics, total_files } = data

  const languageEntries = Object.entries(languages)
  if (languageEntries.length > 0) {
    const [topLanguage, topCount] = languageEntries[0]
    const share = Math.round((topCount / total_files) * 100)
    if (share >= 40) {
      insights.push({
        title: `Primarily ${topLanguage}`,
        body: `${share}% of the ${total_files} analyzed files are ${topLanguage}.`,
      })
    } else if (languageEntries.length > 1) {
      insights.push({
        title: 'Multi-language repository',
        body: `Spans ${languageEntries.length} languages, led by ${topLanguage} and ${languageEntries[1][0]}.`,
      })
    }
  }

  const topFolders = computeTopFolders(data.files)
  const bigFolders = topFolders.filter(([, count]) => count >= 10)
  if (bigFolders.length >= 3) {
    const names = bigFolders.slice(0, 3).map(([name]) => name)
    insights.push({
      title: 'Multi-package structure',
      body: `${names.join(', ')} are each substantial, independently-organized areas of the codebase.`,
    })
  }

  if (statistics.largest_file) {
    const { path, lines, size_bytes } = statistics.largest_file
    // A binary/non-text file (a 3D model, image, lockfile, ...) has no
    // meaningful line count -- "0 lines long" reads as broken, not honest.
    const description = lines > 0 ? `${lines.toLocaleString()} lines long` : `${formatBytes(size_bytes)} on disk`
    insights.push({
      title: 'Largest file',
      body: `${path} is ${description}.`,
    })
  }

  if (frameworks.length > 0) {
    insights.push({
      title: 'Detected frameworks',
      body: `Built with ${frameworks.join(', ')}.`,
    })
  }

  if (healthCache?.findings?.length > 0) {
    const top = healthCache.findings[0]
    insights.push({
      title: top.severity === 'high' ? 'Potential hotspot' : 'Worth reviewing',
      body: top.reason,
    })
  }

  if (gitSummary?.has_git_history && gitSummary.activity.most_modified_files.length > 0) {
    const [hotFile] = gitSummary.activity.most_modified_files
    insights.push({
      title: 'Frequently changed',
      body: `${hotFile.path} has been modified in ${hotFile.commit_count} commits.`,
    })
  }

  return insights.slice(0, 5)
}

export function RepositoryOverview({ data, onExploreStructure }) {
  const [mode, setMode] = useState('beginner')
  const summary = useQuery({
    queryKey: ['repository-summary'],
    queryFn: generateRepositorySummary,
    retry: false,
    staleTime: Infinity,
  })
  const gitSummary = useQuery({ queryKey: ['git-summary'], queryFn: fetchGitSummary, retry: false })

  const { total_files, total_folders, languages, frameworks, statistics } = data
  const topFolders = computeTopFolders(data.files)
  const insights = buildInsights(data, gitSummary.data, null)
  const contributors = gitSummary.data?.has_git_history ? gitSummary.data.activity.contributors : null

  return (
    <div className="overview">
      <section className="overview-identity">
        <h1>{data.repository_name}</h1>
        <p className="card-subtitle">Repository analysis</p>

        {summary.data && (
          <div className="mode-toggle mt-6">
            <button
              type="button"
              className={mode === 'beginner' ? 'mode-btn mode-btn-active' : 'mode-btn'}
              onClick={() => setMode('beginner')}
            >
              Beginner
            </button>
            <button
              type="button"
              className={mode === 'developer' ? 'mode-btn mode-btn-active' : 'mode-btn'}
              onClick={() => setMode('developer')}
            >
              Developer
            </button>
          </div>
        )}

        {summary.isPending && <p className="card-subtitle mt-3">Generating a summary of this repository…</p>}
        {summary.isError && (
          <p className="card-subtitle mt-3">Could not generate an AI summary: {errorMessage(summary.error)}</p>
        )}
        {summary.data && (
          <p className="summary-text">
            {mode === 'beginner' ? summary.data.beginner_summary : summary.data.developer_summary}
          </p>
        )}
      </section>

      <div className="metrics-row">
        <span>
          <strong>{total_files}</strong> files
        </span>
        <span>
          <strong>{total_folders}</strong> folders
        </span>
        <span>
          <strong>{statistics.total_lines.toLocaleString()}</strong> lines
        </span>
        {contributors != null && (
          <span>
            <strong>{contributors}</strong> contributors
          </span>
        )}
      </div>

      <div className="overview-grid">
        <section className="overview-block">
          <h2>Repository structure</h2>
          {topFolders.length > 0 ? (
            <ul className="structure-summary-list">
              {topFolders.map(([name, count]) => (
                <li key={name} className="structure-summary-row">
                  <span className="structure-summary-name">{name === '(root)' ? name : `${name}/`}</span>
                  <span className="structure-summary-count">{count} files</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="card-subtitle">No files found.</p>
          )}
          <button type="button" className="link-button" onClick={onExploreStructure}>
            Explore structure →
          </button>
        </section>

        <section className="overview-block">
          <h2>Tech stack</h2>
          {Object.keys(languages).length > 0 || frameworks.length > 0 ? (
            <ul className="tag-list">
              {Object.entries(languages).map(([language, count]) => (
                <li key={language} className="tag">
                  {language}
                  <span className="tag-count">{count}</span>
                </li>
              ))}
              {frameworks.map((framework) => (
                <li key={framework} className="tag">
                  {framework}
                </li>
              ))}
            </ul>
          ) : (
            <p className="card-subtitle">No recognized languages or frameworks found.</p>
          )}
        </section>
      </div>

      <section className="overview-block">
        <h2>Key insights</h2>
        {insights.length > 0 ? (
          <ol className="insight-list">
            {insights.map((insight, index) => (
              <li key={insight.title} className="insight-item">
                <span className="insight-index">{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <p className="insight-title">{insight.title}</p>
                  <p className="insight-body">{insight.body}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="card-subtitle">Nothing notable surfaced yet.</p>
        )}
      </section>
    </div>
  )
}
