import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { RepositoryGraph } from '@/components/RepositoryGraph/RepositoryGraph'
import { FileDetailsPanel } from '@/components/FileDetailsPanel'
import {
  analyzeChangeImpact,
  ApiError,
  askRepositoryQuestion,
  exportPdf,
  fetchCodeIntelligence,
  fetchGitSummary,
  fetchRepositoryAnalysis,
  fetchRepositoryGraph,
  fetchRepositoryHealth,
  generateRepositorySummary,
} from '@/api'
import { buildJsonExport, buildMarkdownReport, downloadBlob, downloadTextFile } from '@/lib/build-report'

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

function ArchitectureTab() {
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

  const explain = useMutation({ mutationFn: askRepositoryQuestion })
  const impact = useMutation({ mutationFn: analyzeChangeImpact })

  function handleModeChange(nextMode) {
    setMode(nextMode)
    if (MODE_PRESETS[nextMode]) setRelationshipFilter(MODE_PRESETS[nextMode].relationshipFilter)
  }

  function handleExplain(path) {
    explain.mutate(
      { question: `Explain the purpose and implementation of the file ${path}.`, mode: 'developer' },
      { onError: (error) => toast.error('Could not explain file', { description: errorMessage(error) }) },
    )
  }

  function selectNode(node) {
    setSelectedNode(node)
    explain.reset()
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
    explain.reset()
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

  if (graphQuery.isPending) {
    return (
      <div className="panel">
        <p className="card-subtitle">Building repository graph…</p>
      </div>
    )
  }

  if (graphQuery.isError) {
    return (
      <div className="panel">
        <h2 className="panel-title">Could not load graph</h2>
        <p className="card-subtitle">{graphQuery.error.message}</p>
      </div>
    )
  }

  return (
    <>
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

        <FileDetailsPanel
          node={selectedNode}
          intelligence={intelligenceQuery.data}
          onExplain={handleExplain}
          explain={explain}
        />
      </div>
    </>
  )
}

function formatDate(iso) {
  if (!iso) return 'unknown date'
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

function GitTab() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['git-summary'],
    queryFn: fetchGitSummary,
    retry: false,
  })

  if (isPending) {
    return (
      <div className="panel">
        <p className="card-subtitle">Reading Git history…</p>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="panel">
        <h2 className="panel-title">Could not load Git history</h2>
        <p className="card-subtitle">{errorMessage(error)}</p>
      </div>
    )
  }

  if (!data.has_git_history) {
    return (
      <div className="panel">
        <h2 className="panel-title">No Git history available</h2>
        <p className="card-subtitle">This repository may not contain Git metadata.</p>
      </div>
    )
  }

  const { latest_commit, activity, timeline } = data

  return (
    <>
      {latest_commit && (
        <div className="panel">
          <h2 className="panel-title">Latest Commit</h2>
          <p className="card-title">{latest_commit.message}</p>
          <p className="card-subtitle">
            {latest_commit.author} · {formatDate(latest_commit.date)}
          </p>
          <span className="commit-hash mt-3" style={{ display: 'inline-block' }}>
            {latest_commit.short_hash}
          </span>
        </div>
      )}

      <div className="stat-grid">
        <div className="panel">
          <p className="stat-label">Commits analyzed</p>
          <p className="stat-value">
            {activity.total_commits}
            {activity.truncated ? '+' : ''}
          </p>
        </div>
        <div className="panel">
          <p className="stat-label">Contributors</p>
          <p className="stat-value">{activity.contributors}</p>
        </div>
        <div className="panel">
          <p className="stat-label">Last 7 days</p>
          <p className="stat-value">{activity.commits_last_7_days}</p>
        </div>
        <div className="panel">
          <p className="stat-label">Last 30 days</p>
          <p className="stat-value">{activity.commits_last_30_days}</p>
        </div>
      </div>
      {activity.truncated && (
        <p className="git-stat-note">
          Statistics are based on the most recently analyzed {activity.analyzed_commit_count} commits.
        </p>
      )}

      <div className="analysis-columns">
        <div className="panel">
          <h2 className="panel-title">Timeline</h2>
          {timeline.length > 0 ? (
            <ul className="timeline">
              {timeline.map((commit) => (
                <li key={commit.hash} className="timeline-item">
                  <p className="timeline-date">{formatDate(commit.date)}</p>
                  <p className="timeline-message">{commit.message}</p>
                  <p className="timeline-meta">
                    {commit.author} · <span className="commit-hash">{commit.short_hash}</span> · {commit.files_changed} file
                    {commit.files_changed === 1 ? '' : 's'}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="card-subtitle">No commits found.</p>
          )}
        </div>

        <div className="panel">
          <h2 className="panel-title">Most Changed Files</h2>
          {activity.most_modified_files.length > 0 ? (
            <ul className="hotspot-list">
              {activity.most_modified_files.map((file) => (
                <li key={file.path} className="hotspot-row">
                  <span className="hotspot-path">{file.path}</span>
                  <span className="hotspot-count">{file.commit_count} commits</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="card-subtitle">No file history available.</p>
          )}
        </div>
      </div>
    </>
  )
}

function HealthTab() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['repository-health'],
    queryFn: fetchRepositoryHealth,
    retry: false,
  })

  if (isPending) {
    return (
      <div className="panel">
        <p className="card-subtitle">Analyzing repository health…</p>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="panel">
        <h2 className="panel-title">Could not analyze repository health</h2>
        <p className="card-subtitle">{errorMessage(error)}</p>
      </div>
    )
  }

  const { score, categories, findings } = data

  return (
    <>
      <div className="panel">
        <h2 className="panel-title">CodeMap Health Score</h2>
        <div className="health-score-hero">
          <div className="health-score-ring">
            <span className="health-score-ring-value">{score}</span>
            <span className="health-score-ring-label">/ 100</span>
          </div>
          <div className="health-category-grid">
            {Object.entries(categories).map(([category, categoryScore]) => (
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
        <p className="git-stat-note mt-6">
          Heuristic structural estimate based on file size, test/README presence, import-graph shape, and declared
          dependencies — not a substitute for a linter or security scanner.
        </p>
      </div>

      <div className="panel">
        <h2 className="panel-title">Findings</h2>
        {findings.length > 0 ? (
          <ul className="finding-list">
            {findings.map((finding, index) => (
              <li key={index} className={`finding-item finding-item-${finding.severity}`}>
                <div className="finding-header">
                  <span className={`finding-severity finding-severity-${finding.severity}`}>{finding.severity}</span>
                  <span className="finding-category">{finding.category}</span>
                  {finding.path && <span className="finding-path">{finding.path}</span>}
                </div>
                <p className="finding-reason">{finding.reason}</p>
                <p className="finding-recommendation">{finding.recommendation}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="card-subtitle">No issues found by the heuristic checks.</p>
        )}
      </div>
    </>
  )
}

function ExportTab({ repositoryAnalysis }) {
  const queryClient = useQueryClient()
  const codeIntelligenceQuery = useQuery({ queryKey: ['code-intelligence'], queryFn: fetchCodeIntelligence, retry: false })
  const healthQuery = useQuery({ queryKey: ['repository-health'], queryFn: fetchRepositoryHealth, retry: false })
  const gitQuery = useQuery({ queryKey: ['git-summary'], queryFn: fetchGitSummary, retry: false })
  const summary = useMutation({ mutationFn: generateRepositorySummary })
  const pdfExport = useMutation({ mutationFn: exportPdf })

  const lastImpact = queryClient.getQueryData(['last-impact-result']) ?? null

  function collectData() {
    return {
      repositoryAnalysis,
      codeIntelligence: codeIntelligenceQuery.data ?? null,
      health: healthQuery.data ?? null,
      gitSummary: gitQuery.data ?? null,
      beginnerSummary: summary.data?.beginner_summary ?? null,
      developerSummary: summary.data?.developer_summary ?? null,
      lastImpact,
    }
  }

  function handleGenerateSummary() {
    summary.mutate(undefined, {
      onError: (error) => toast.error('Could not generate AI summary', { description: errorMessage(error) }),
    })
  }

  function handleDownloadMarkdown() {
    const markdown = buildMarkdownReport(collectData())
    downloadTextFile(`codemap-${repositoryAnalysis.repository_name}.md`, markdown, 'text/markdown')
  }

  async function handleDownloadJson() {
    let graph = null
    try {
      graph = await fetchRepositoryGraph({})
    } catch {
      graph = null // JSON export still works without the graph -- it's supplementary
    }
    const json = buildJsonExport({ ...collectData(), graph })
    downloadTextFile(`codemap-${repositoryAnalysis.repository_name}.json`, JSON.stringify(json, null, 2), 'application/json')
  }

  function handleDownloadPdf() {
    const markdown = buildMarkdownReport(collectData())
    pdfExport.mutate(
      { title: `CodeMap Repository Report - ${repositoryAnalysis.repository_name}`, markdown },
      {
        onSuccess: (blob) => downloadBlob(`codemap-${repositoryAnalysis.repository_name}.pdf`, blob),
        onError: (error) => toast.error('Could not generate PDF', { description: errorMessage(error) }),
      },
    )
  }

  async function handleCopyMarkdown() {
    const markdown = buildMarkdownReport(collectData())
    try {
      await navigator.clipboard.writeText(markdown)
      toast.success('Markdown report copied to clipboard')
    } catch {
      toast.error('Could not copy to clipboard')
    }
  }

  const checklist = [
    { label: 'Repository overview & tech stack', included: true },
    { label: 'AI summaries', included: Boolean(summary.data) },
    { label: 'Code intelligence & architecture', included: Boolean(codeIntelligenceQuery.data) },
    { label: 'Repository health', included: Boolean(healthQuery.data) },
    { label: 'Git history', included: Boolean(gitQuery.data?.has_git_history) },
    { label: 'Impact analysis', included: Boolean(lastImpact) },
  ]

  return (
    <div className="export-grid">
      <div className="panel">
        <h2 className="panel-title">Report contents</h2>
        <p className="card-subtitle">
          The report is built from what CodeMap has already analyzed in this session. Visit a tab (Architecture,
          Git, Health) before exporting to include it, or generate the AI summary below.
        </p>
        <ul className="export-checklist">
          {checklist.map((item) => (
            <li key={item.label} className={item.included ? '' : 'export-checklist-missing'}>
              {item.label}
            </li>
          ))}
        </ul>

        <button
          type="button"
          className="btn btn-outline btn-block mt-6"
          onClick={handleGenerateSummary}
          disabled={summary.isPending}
        >
          {summary.isPending ? 'Generating…' : summary.data ? 'Regenerate AI Summary' : 'Generate AI Summary for Report'}
        </button>
      </div>

      <div className="panel">
        <h2 className="panel-title">Export</h2>
        <div className="export-format-list">
          <button type="button" className="btn btn-primary btn-block" onClick={handleDownloadMarkdown}>
            Download Markdown
          </button>
          <button type="button" className="btn btn-outline btn-block" onClick={handleDownloadJson}>
            Download JSON
          </button>
          <button
            type="button"
            className="btn btn-outline btn-block"
            onClick={handleDownloadPdf}
            disabled={pdfExport.isPending}
          >
            {pdfExport.isPending ? 'Generating PDF…' : 'Download PDF'}
          </button>
        </div>

        <h2 className="panel-title mt-6">Share</h2>
        <p className="card-subtitle">
          Full persistent share links are planned for a future version. For now, copy or download the report to
          share it directly.
        </p>
        <button type="button" className="btn btn-outline btn-block mt-3" onClick={handleCopyMarkdown}>
          Copy Markdown to Clipboard
        </button>
      </div>
    </div>
  )
}

function FolderTreeView({ tree }) {
  const entries = Object.entries(tree)
  if (entries.length === 0) return null

  return (
    <ul className="folder-tree">
      {entries.map(([name, children]) => (
        <li key={name}>
          <span className="folder-tree-name">{name}</span>
          <FolderTreeView tree={children} />
        </li>
      ))}
    </ul>
  )
}

function OverviewTab({ data }) {
  const { total_files, total_folders, languages, frameworks, folder_tree, statistics } = data
  const hasFolders = Object.keys(folder_tree).length > 0

  return (
    <>
      <div className="stat-grid">
        <div className="panel">
          <p className="stat-label">Total files</p>
          <p className="stat-value">{total_files}</p>
        </div>
        <div className="panel">
          <p className="stat-label">Total folders</p>
          <p className="stat-value">{total_folders}</p>
        </div>
        <div className="panel">
          <p className="stat-label">Total lines</p>
          <p className="stat-value">{statistics.total_lines}</p>
        </div>
        <div className="panel">
          <p className="stat-label">Largest file</p>
          <p className="stat-value stat-value-small">
            {statistics.largest_file ? statistics.largest_file.path : '—'}
          </p>
        </div>
      </div>

      <div className="analysis-columns">
        <div className="panel">
          <h2 className="panel-title">Languages</h2>
          {Object.keys(languages).length > 0 ? (
            <ul className="tag-list">
              {Object.entries(languages).map(([language, count]) => (
                <li key={language} className="tag">
                  {language}
                  <span className="tag-count">{count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="card-subtitle">No recognized languages found.</p>
          )}
        </div>

        <div className="panel">
          <h2 className="panel-title">Frameworks</h2>
          {frameworks.length > 0 ? (
            <ul className="tag-list">
              {frameworks.map((framework) => (
                <li key={framework} className="tag">
                  {framework}
                </li>
              ))}
            </ul>
          ) : (
            <p className="card-subtitle">No frameworks detected.</p>
          )}
        </div>
      </div>

      <div className="panel">
        <h2 className="panel-title">Folder structure</h2>
        {hasFolders ? <FolderTreeView tree={folder_tree} /> : <p className="card-subtitle">No subfolders found.</p>}
      </div>
    </>
  )
}

export function AnalysisPage({ onBack, onViewInsights }) {
  const [tab, setTab] = useState('overview')
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['repository-analysis'],
    queryFn: fetchRepositoryAnalysis,
  })

  if (isPending) {
    return (
      <div className="app-shell">
        <div className="app-glow" />
        <div className="app-content">
          <header className="app-header">
            <div className="logo-mark">C</div>
            <span className="logo-text">CodeMap</span>
          </header>
          <main className="app-main">
            <div className="panel card-center">
              <p className="card-title">Analyzing repository…</p>
              <ul className="progress-stage-list">
                <li className="progress-stage progress-stage-done">
                  <span className="progress-stage-icon">
                    <CheckCircle2 size={16} />
                  </span>
                  Repository imported
                </li>
                <li className="progress-stage">
                  <span className="progress-stage-icon">
                    <Loader2 className="spinner" size={16} />
                  </span>
                  Scanning files and mapping structure…
                </li>
              </ul>
              <p className="git-stat-note mt-6">
                Code intelligence, Git history, health analysis, and AI summaries are generated on demand as you
                open each tab.
              </p>
            </div>
          </main>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="app-shell">
        <div className="app-glow" />
        <div className="app-content">
          <header className="app-header">
            <div className="logo-mark">C</div>
            <span className="logo-text">CodeMap</span>
          </header>
          <main className="app-main">
            <div className="panel">
              <h1 className="card-title">Repository could not be analyzed</h1>
              <p className="card-subtitle">{error.message}</p>
              <button className="btn btn-outline btn-block mt-6" onClick={onBack}>
                Back
              </button>
            </div>
          </main>
        </div>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <div className="app-glow" />
      <div className="app-content">
        <header className="app-header">
          <div className="logo-mark">C</div>
          <span className="logo-text">CodeMap</span>
        </header>
        <main className="app-main">
          <div className="analysis-page">
            <div className="analysis-header">
              <div>
                <h1 className="card-title">{data.repository_name}</h1>
                <p className="card-subtitle">Repository analysis</p>
              </div>
              <div className="button-row">
                <button className="btn btn-primary" onClick={onViewInsights}>
                  Ask CodeMap
                </button>
                <button className="btn btn-outline" onClick={onBack}>
                  Import another repository
                </button>
              </div>
            </div>

            <div className="mode-toggle">
              <button
                type="button"
                className={tab === 'overview' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                onClick={() => setTab('overview')}
              >
                Overview
              </button>
              <button
                type="button"
                className={tab === 'architecture' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                onClick={() => setTab('architecture')}
              >
                Architecture
              </button>
              <button
                type="button"
                className={tab === 'git' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                onClick={() => setTab('git')}
              >
                Git
              </button>
              <button
                type="button"
                className={tab === 'health' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                onClick={() => setTab('health')}
              >
                Health
              </button>
              <button
                type="button"
                className={tab === 'export' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                onClick={() => setTab('export')}
              >
                Export
              </button>
            </div>

            {tab === 'overview' && <OverviewTab data={data} />}
            {tab === 'architecture' && <ArchitectureTab />}
            {tab === 'git' && <GitTab />}
            {tab === 'health' && <HealthTab />}
            {tab === 'export' && <ExportTab repositoryAnalysis={data} />}
          </div>
        </main>
      </div>
    </div>
  )
}
