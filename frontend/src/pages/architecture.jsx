import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { RepositoryGraph } from '@/RepositoryGraph'
import { analyzeChangeImpact, ApiError, fetchCodeIntelligence, fetchFileGitHistory, fetchRepositoryGraph } from '@/api'
import '../css/architecture.css'

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

const NODE_TYPE_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'file', label: 'Files' },
  { id: 'folder', label: 'Folders' },
  { id: 'external', label: 'External' },
]

const MODE_LABELS = {
  architecture: 'Repository Map',
  dependencies: 'Dependencies',
  impact: 'Impact Analysis',
}

const MODE_PRESETS = {
  architecture: { relationshipFilter: { imports: true, calls: false }, direction: 'TB' },
  dependencies: { relationshipFilter: { imports: true, calls: true }, direction: 'LR' },
}

function impactFileNode(path, impact) {
  return { id: path, type: 'file', data: { label: path.split('/').pop(), path, impact } }
}

function impactToGraphData(impactResult) {
  if (!impactResult) return { nodes: [], edges: [] }
  const nodes = [impactFileNode(impactResult.file, 'target')]
  const edges = []
  for (const dep of [...impactResult.direct_dependents, ...impactResult.indirect_dependents]) {
    nodes.push(impactFileNode(dep.path, dep.depth === 1 ? 'direct' : 'indirect'))
    // Edge points from what changed toward its dependent, so the changed
    // file lands at the top of a top-down layout, matching "if X changes it affects Y".
    dep.via.forEach((type) => {
      edges.push({
        id: `impact-${dep.discovered_via}-${dep.path}-${type}`,
        source: dep.discovered_via,
        target: dep.path,
        type,
        weight: 1,
      })
    })
  }
  return { nodes, edges }
}

// Accepts { path, type } entries -- type is "file" for a leaf file node, or
// "folder" for a real folder-graph-node (the repository-map's aggregated
// view, used for large repos, only ever returns folder/external nodes, no
// file nodes -- without this, a big repo's sidebar had nothing to show).
// Path segments with no matching entry are still rendered, just inert.
function buildFileTree(entries) {
  const root = {}
  for (const { path, type } of entries) {
    const parts = path.split('/')
    let cursor = root
    parts.forEach((part, index) => {
      const isTerminal = index === parts.length - 1
      cursor[part] ??= { name: part, path: parts.slice(0, index + 1).join('/'), isSelectable: false, isFolder: false }
      if (isTerminal) {
        cursor[part].isSelectable = true
        cursor[part].isFolder = type === 'folder'
      }
      if (index < parts.length - 1) {
        cursor[part].children ??= {}
      }
      cursor = cursor[part].children ?? cursor
    })
  }
  return root
}

function FileTree({ nodes, selectedPath, onSelect }) {
  const entries = Object.values(nodes).sort(
    (a, b) => Number(a.isSelectable) - Number(b.isSelectable) || a.name.localeCompare(b.name),
  )

  return (
    <ul className="file-tree">
      {entries.map((entry) => (
        <li key={entry.path}>
          {entry.isSelectable ? (
            <button
              type="button"
              className={`file-tree-item${entry.path === selectedPath ? ' file-tree-item-active' : ''}`}
              onClick={() => onSelect(entry.path)}
            >
              {entry.isFolder ? `${entry.name}/` : entry.name}
            </button>
          ) : (
            <span className="file-tree-folder">{entry.name}</span>
          )}
          {entry.children && <FileTree nodes={entry.children} selectedPath={selectedPath} onSelect={onSelect} />}
        </li>
      ))}
    </ul>
  )
}

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

function FileInspector({ node, intelligence, onAskAbout }) {
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

      <button type="button" className="btn btn-outline btn-block mt-6" onClick={() => onAskAbout(node.data.path)}>
        Explain this file
      </button>
    </div>
  )
}

export function ArchitectureWorkspace({ onAskAbout }) {
  const [mode, setMode] = useState('architecture')
  const [focus, setFocus] = useState(null)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [relationshipFilter, setRelationshipFilter] = useState(MODE_PRESETS.architecture.relationshipFilter)
  const [selectedNode, setSelectedNode] = useState(null)
  const [fitSignal, setFitSignal] = useState(0)
  const [centerRequest, setCenterRequest] = useState(null)
  const queryClient = useQueryClient()

  const graphQuery = useQuery({
    queryKey: ['repository-graph', focus],
    queryFn: () => fetchRepositoryGraph({ focus }),
  })

  // Only fetch once the graph call has succeeded: /repository/graph builds and
  // stores code intelligence on demand, so this is guaranteed to exist by then
  // instead of racing a second on-demand build.
  const intelligenceQuery = useQuery({
    queryKey: ['code-intelligence'],
    queryFn: fetchCodeIntelligence,
    retry: false,
    enabled: graphQuery.isSuccess,
  })

  const impact = useMutation({ mutationFn: analyzeChangeImpact })

  function handleModeChange(nextMode) {
    setMode(nextMode)
    if (MODE_PRESETS[nextMode]) setRelationshipFilter(MODE_PRESETS[nextMode].relationshipFilter)
  }

  // Routes to the one Ask CodeMap experience on Overview instead of running
  // its own separate AI call and rendering the answer inline here.
  function handleAskAboutFile(path) {
    onAskAbout(`Explain the purpose and implementation of the file ${path}.`)
  }

  function selectNode(node) {
    setSelectedNode(node)
  }

  function handleAnalyzeImpact() {
    if (selectedNode?.type !== 'file') {
      toast.error('Select a file in the tree first.')
      return
    }
    impact.mutate(
      { file: selectedNode.data.path },
      {
        onSuccess: (data) => {
          selectNode(impactFileNode(data.file, 'target'))
          queryClient.setQueryData(['last-impact-result'], data)
        },
        onError: (error) => toast.error('Could not analyze impact', { description: errorMessage(error) }),
      },
    )
  }

  function handleGraphNodeClick(rfNode) {
    const original = displayedNodes.find((node) => node.id === rfNode.id)
    if (!original) return
    selectNode(original)
    if (original.type === 'folder' && (mode === 'architecture' || mode === 'dependencies')) {
      setFocus(original.id)
    }
  }

  function handleTreeSelect(path) {
    const original = graphQuery.data?.nodes.find((node) => node.id === path)
    if (!original) return
    selectNode(original)
    if (original.type === 'folder') {
      setFocus(original.id)
    } else {
      setCenterRequest({ nodeId: path, key: Date.now() })
    }
  }

  function handleReset() {
    setFocus(null)
    setSearch('')
    setTypeFilter('all')
    if (MODE_PRESETS[mode]) setRelationshipFilter(MODE_PRESETS[mode].relationshipFilter)
    setSelectedNode(null)
    impact.reset()
  }

  const rawNodes = graphQuery.data?.nodes ?? []
  const rawEdges = graphQuery.data?.edges ?? []

  const filteredNodes = useMemo(
    () => rawNodes.filter((node) => typeFilter === 'all' || node.type === typeFilter),
    [rawNodes, typeFilter],
  )
  const filteredNodeIds = useMemo(() => new Set(filteredNodes.map((node) => node.id)), [filteredNodes])
  const filteredEdges = useMemo(
    () =>
      rawEdges.filter(
        (edge) => relationshipFilter[edge.type] && filteredNodeIds.has(edge.source) && filteredNodeIds.has(edge.target),
      ),
    [rawEdges, relationshipFilter, filteredNodeIds],
  )

  const highlightedIds = useMemo(() => {
    if (mode !== 'architecture' && mode !== 'dependencies') return null
    const term = search.trim().toLowerCase()
    if (!term) return null
    const matched = new Set(
      filteredNodes
        .filter((node) => node.data.label.toLowerCase().includes(term) || (node.data.path ?? '').toLowerCase().includes(term))
        .map((node) => node.id),
    )
    filteredEdges.forEach((edge) => {
      if (matched.has(edge.source)) matched.add(edge.target)
      if (matched.has(edge.target)) matched.add(edge.source)
    })
    return matched
  }, [mode, search, filteredNodes, filteredEdges])

  const fileTree = useMemo(
    () =>
      buildFileTree(
        rawNodes
          .filter((node) => node.type === 'file' || node.type === 'folder')
          .map((node) => ({ path: node.data.path, type: node.type })),
      ),
    [rawNodes],
  )

  const impactGraph = useMemo(() => impactToGraphData(impact.data), [impact.data])

  const displayedNodes = mode === 'impact' ? impactGraph.nodes : filteredNodes
  const displayedEdges = mode === 'impact' ? impactGraph.edges : filteredEdges
  const direction = MODE_PRESETS[mode]?.direction ?? 'TB'

  return (
    <div className="architecture-workspace">
      <h1 className="subview-heading">Architecture</h1>

      <div className="architecture-toolbar">
        <div className="mode-toggle">
          {Object.keys(MODE_LABELS).map((m) => (
            <button
              key={m}
              type="button"
              className={mode === m ? 'mode-btn mode-btn-active' : 'mode-btn'}
              onClick={() => handleModeChange(m)}
            >
              {MODE_LABELS[m]}
            </button>
          ))}
        </div>

        {(mode === 'architecture' || mode === 'dependencies') && (
          <>
            <input
              className="input architecture-search"
              type="text"
              placeholder="Search files or functions…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />

            <div className="filter-group">
              <span className="filter-group-label">Show</span>
              {NODE_TYPE_FILTERS.map((filter) => (
                <button
                  key={filter.id}
                  type="button"
                  className={`filter-chip${typeFilter === filter.id ? ' filter-chip-active' : ''}`}
                  onClick={() => setTypeFilter(filter.id)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </>
        )}

        {mode === 'impact' && (
          <button type="button" className="btn btn-primary" onClick={handleAnalyzeImpact} disabled={impact.isPending}>
            {impact.isPending ? 'Analyzing…' : 'Analyze Impact'}
          </button>
        )}

        {(mode === 'architecture' || mode === 'dependencies') && (
          <div className="filter-group">
            <span className="filter-group-label">Relationships</span>
            {['imports', 'calls'].map((type) => (
              <button
                key={type}
                type="button"
                className={`filter-chip${relationshipFilter[type] ? ' filter-chip-active' : ''}`}
                onClick={() => setRelationshipFilter((prev) => ({ ...prev, [type]: !prev[type] }))}
              >
                {type === 'imports' ? 'Imports' : 'Calls'}
              </button>
            ))}
          </div>
        )}

        <div className="button-row">
          <button type="button" className="btn btn-outline" onClick={() => setFitSignal((n) => n + 1)}>
            Fit Graph
          </button>
          <button type="button" className="btn btn-outline" onClick={handleReset}>
            Reset
          </button>
        </div>
      </div>

      {graphQuery.isPending && (
        <div className="panel">
          <p className="card-subtitle">Building repository graph…</p>
        </div>
      )}

      {graphQuery.isError && (
        <div className="panel">
          <h2 className="panel-title">Could not load graph</h2>
          <p className="card-subtitle">{graphQuery.error.message}</p>
        </div>
      )}

      {graphQuery.isSuccess && (
        <>
          {(mode === 'architecture' || mode === 'dependencies') && graphQuery.data.truncated && (
            <div className="architecture-banner">{graphQuery.data.message}</div>
          )}

          {mode === 'impact' && impact.data && (
            <div className="panel impact-report">
              <div className="impact-report-header">
                <h2 className="panel-title">Impact of changing {impact.data.file}</h2>
                <span className={`risk-badge risk-${impact.data.risk.level}`}>
                  {impact.data.risk.level.toUpperCase()} · {impact.data.risk.score}
                </span>
              </div>
              <p className="card-subtitle">
                {impact.data.direct_dependents.length} direct dependent(s), {impact.data.indirect_dependents.length}{' '}
                indirect dependent(s)
                {impact.data.related_routes.length > 0 ? `, ${impact.data.related_routes.length} related route(s)` : ''}
                {impact.data.related_files.length > 0 ? `, ${impact.data.related_files.length} related frontend file(s)` : ''}.
              </p>
              {impact.data.summary ? (
                <p className="summary-text">{impact.data.summary}</p>
              ) : (
                <p className="card-subtitle">AI explanation unavailable (no AI provider configured for this backend).</p>
              )}
            </div>
          )}
          {mode === 'impact' && impact.isError && <div className="architecture-banner">{errorMessage(impact.error)}</div>}
          {mode === 'impact' && !impact.data && !impact.isPending && !impact.isError && (
            <div className="architecture-banner">Select a file in the file tree and click &ldquo;Analyze Impact&rdquo;.</div>
          )}

          <div className="architecture-layout">
            <div className="architecture-sidebar">
              <p className="architecture-sidebar-title">Files</p>
              <FileTree nodes={fileTree} selectedPath={selectedNode?.data?.path} onSelect={handleTreeSelect} />
            </div>

            <RepositoryGraph
              nodes={displayedNodes}
              edges={displayedEdges}
              direction={direction}
              selectedNodeId={selectedNode?.id}
              highlightedIds={highlightedIds}
              onNodeClick={handleGraphNodeClick}
              fitSignal={fitSignal}
              centerRequest={centerRequest}
            />

            <FileInspector node={selectedNode} intelligence={intelligenceQuery.data} onAskAbout={handleAskAboutFile} />
          </div>
        </>
      )}
    </div>
  )
}
