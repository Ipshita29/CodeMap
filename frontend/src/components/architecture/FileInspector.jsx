import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { fetchFileGitHistory } from '@/api'
import './FileInspector.css'

function computeFileDetails(path, intelligence) {
  if (!intelligence) return null

  const functions = intelligence.symbols.filter((symbol) => symbol.kind === 'function' && symbol.file === path)
  const classes = intelligence.symbols.filter((symbol) => symbol.kind === 'class' && symbol.file === path)
  const exports = intelligence.exports.filter((entry) => entry.file === path)
  const imports = intelligence.imports.filter((entry) => entry.file === path)
  const importedBy = [
    ...new Set(
      intelligence.relationships.filter((rel) => rel.type === 'imports' && rel.target === path).map((rel) => rel.source),
    ),
  ]

  return { functions, classes, exports, imports, importedBy }
}

function DetailsSection({ title, items, render, emptyLabel = 'None' }) {
  return (
    <section className="details-section">
      <h4 className="details-section-title">{title}</h4>
      {items.length > 0 ? (
        <ul className="inspector-list">
          {items.map((item, index) => (
            <li key={index}>{render(item)}</li>
          ))}
        </ul>
      ) : (
        <p className="card-subtitle">{emptyLabel}</p>
      )}
    </section>
  )
}

const IMPACT_LABELS = { target: 'Selected file', direct: 'Direct dependent', indirect: 'Indirect dependent' }

function GitHistorySection({ path }) {
  const [expanded, setExpanded] = useState(false)
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['file-git-history', path],
    queryFn: () => fetchFileGitHistory(path),
    enabled: false,
    retry: false,
  })

  function handleToggle() {
    if (!expanded && !data) refetch()
    setExpanded((prev) => !prev)
  }

  return (
    <section className="details-section">
      <button type="button" className="btn btn-outline btn-block" onClick={handleToggle}>
        {expanded ? 'Hide Git History' : 'View Git History'}
      </button>

      {expanded && (
        <div className="mt-3">
          {isPending && <p className="card-subtitle">Loading history…</p>}
          {isError && (
            <p className="card-subtitle">{error instanceof Error ? error.message : 'Could not load Git history.'}</p>
          )}
          {data && !data.has_git_history && <p className="card-subtitle">No Git history available.</p>}
          {data && data.has_git_history && data.commits.length === 0 && (
            <p className="card-subtitle">No commits found for this file.</p>
          )}
          {data && data.commits.length > 0 && (
            <ul className="timeline">
              {data.commits.map((commit) => (
                <li key={commit.short_hash} className="timeline-item">
                  <p className="timeline-date">{commit.date ? new Date(commit.date).toLocaleDateString() : ''}</p>
                  <p className="timeline-message">{commit.message}</p>
                  <p className="timeline-meta">
                    <span className="commit-hash">{commit.short_hash}</span>
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

export function FileInspector({ node, intelligence, onExplain, explain }) {
  const detailsPath = node?.type === 'file' ? node.data.path : null
  const details = useMemo(() => computeFileDetails(detailsPath, intelligence), [detailsPath, intelligence])

  if (!node) {
    return (
      <div className="file-details-panel">
        <p className="card-subtitle">Select a file to inspect it.</p>
      </div>
    )
  }

  if (node.type === 'folder') {
    return (
      <div className="file-details-panel">
        <h3 className="panel-title">{node.data.label}</h3>
        <p className="card-subtitle">{node.data.file_count} files</p>
        <p className="details-hint">Click this folder again to expand its files and connections.</p>
      </div>
    )
  }

  if (node.type === 'external') {
    return (
      <div className="file-details-panel">
        <h3 className="panel-title">{node.data.label}</h3>
        <p className="card-subtitle">External dependency</p>
      </div>
    )
  }

  return (
    <div className="file-details-panel">
      <h3 className="panel-title">{node.data.label}</h3>
      <p className="details-path">{node.data.path}</p>

      <div className="details-tags">
        {node.data.impact && <span className="tag">{IMPACT_LABELS[node.data.impact]}</span>}
        {node.data.language && <span className="tag">{node.data.language}</span>}
        {node.data.lines != null && <span className="tag">{node.data.lines} lines</span>}
      </div>

      {node.data.parse_error && (
        <p className="field-error">
          This file could not be analyzed. The language or syntax may be unsupported, or the file is too large.
        </p>
      )}

      {details && (
        <>
          <DetailsSection title="Functions" items={details.functions} render={(fn) => fn.name} />
          <DetailsSection title="Classes" items={details.classes} render={(cls) => cls.name} />
          <DetailsSection title="Exports" items={details.exports} render={(exp) => `${exp.name} (${exp.kind})`} />
          <DetailsSection title="Imports" items={details.imports} render={(imp) => imp.source} />
          <DetailsSection title="Imported by" items={details.importedBy} render={(path) => path} />
        </>
      )}

      <GitHistorySection key={node.data.path} path={node.data.path} />

      <button
        type="button"
        className="btn btn-outline btn-block mt-6"
        onClick={() => onExplain(node.data.path)}
        disabled={explain.isPending}
      >
        {explain.isPending ? 'Explaining…' : 'Explain this file'}
      </button>

      {explain.data && (
        <div className="details-explanation">
          <p className="summary-text">{explain.data.answer}</p>
        </div>
      )}
    </div>
  )
}
