import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { RepositoryGraph } from '@/components/RepositoryGraph/RepositoryGraph'
import { FileDetailsPanel } from '@/components/FileDetailsPanel'
import {
  analyzeChangeImpact,
  ApiError,
  askRepositoryQuestion,
  fetchCodeIntelligence,
  fetchRepositoryAnalysis,
  fetchRepositoryGraph,
  runCodeAnalysis,
  traceExecutionFlow,
} from '@/api'

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
  architecture: 'Architecture',
  dependencies: 'Dependencies',
  flow: 'Execution Flow',
  impact: 'Impact Analysis',
}

const MODE_PRESETS = {
  architecture: { relationshipFilter: { imports: true, calls: false }, direction: 'TB' },
  dependencies: { relationshipFilter: { imports: true, calls: true }, direction: 'LR' },
}

function flowNodeToGraphNode(n) {
  return { id: n.id, type: n.type, data: { label: n.name, path: n.path, method: n.method } }
}

function flowToGraphData(flowResult) {
  if (!flowResult) return { nodes: [], edges: [] }
  return {
    nodes: flowResult.flow.map(flowNodeToGraphNode),
    edges: flowResult.relationships.map((r, i) => ({
      id: `flow-${i}-${r.source}-${r.target}`,
      source: r.source,
      target: r.target,
      type: r.type,
      weight: 1,
      confidence: r.confidence,
    })),
  }
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

function buildFileTree(paths) {
  const root = {}
  for (const path of paths) {
    const parts = path.split('/')
    let cursor = root
    parts.forEach((part, index) => {
      cursor[part] ??= { name: part, path: parts.slice(0, index + 1).join('/'), isFile: index === parts.length - 1 }
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
    (a, b) => Number(a.isFile) - Number(b.isFile) || a.name.localeCompare(b.name),
  )

  return (
    <ul className="file-tree">
      {entries.map((entry) => (
        <li key={entry.path}>
          {entry.isFile ? (
            <button
              type="button"
              className={`file-tree-item${entry.path === selectedPath ? ' file-tree-item-active' : ''}`}
              onClick={() => onSelect(entry.path)}
            >
              {entry.name}
            </button>
          ) : (
            <>
              <span className="file-tree-folder">{entry.name}</span>
              {entry.children && <FileTree nodes={entry.children} selectedPath={selectedPath} onSelect={onSelect} />}
            </>
          )}
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
  const [flowQuery, setFlowQuery] = useState('')
  const [flowFunction, setFlowFunction] = useState('')

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
  const flow = useMutation({ mutationFn: traceExecutionFlow })
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

  function handleTraceFlow() {
    const trimmedQuery = flowQuery.trim()
    const payload = trimmedQuery
      ? { query: trimmedQuery }
      : selectedNode?.type === 'file'
        ? { start_file: selectedNode.data.path, start_function: flowFunction.trim() || undefined }
        : null

    if (!payload) {
      toast.error('Select a file in the tree, or describe a feature to trace.')
      return
    }

    flow.mutate(payload, {
      onSuccess: (data) => selectNode(flowNodeToGraphNode(data.start)),
      onError: (error) => toast.error('Could not trace flow', { description: errorMessage(error) }),
    })
  }

  function handleAnalyzeImpact() {
    if (selectedNode?.type !== 'file') {
      toast.error('Select a file in the tree first.')
      return
    }
    impact.mutate(
      { file: selectedNode.data.path },
      {
        onSuccess: (data) => selectNode(impactFileNode(data.file, 'target')),
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
    setCenterRequest({ nodeId: path, key: Date.now() })
  }

  function handleReset() {
    setFocus(null)
    setSearch('')
    setTypeFilter('all')
    if (MODE_PRESETS[mode]) setRelationshipFilter(MODE_PRESETS[mode].relationshipFilter)
    setSelectedNode(null)
    setFlowQuery('')
    setFlowFunction('')
    flow.reset()
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
    () => buildFileTree(rawNodes.filter((node) => node.type === 'file').map((node) => node.data.path)),
    [rawNodes],
  )

  const flowGraph = useMemo(() => flowToGraphData(flow.data), [flow.data])
  const impactGraph = useMemo(() => impactToGraphData(impact.data), [impact.data])

  const displayedNodes = mode === 'flow' ? flowGraph.nodes : mode === 'impact' ? impactGraph.nodes : filteredNodes
  const displayedEdges = mode === 'flow' ? flowGraph.edges : mode === 'impact' ? impactGraph.edges : filteredEdges
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

        {mode === 'flow' && (
          <>
            <input
              className="input architecture-search"
              type="text"
              placeholder="Describe a feature, e.g. authentication…"
              value={flowQuery}
              onChange={(event) => setFlowQuery(event.target.value)}
            />
            <input
              className="input architecture-search"
              type="text"
              placeholder="Start function (optional)"
              value={flowFunction}
              onChange={(event) => setFlowFunction(event.target.value)}
              disabled={Boolean(flowQuery.trim())}
            />
            <button type="button" className="btn btn-primary" onClick={handleTraceFlow} disabled={flow.isPending}>
              {flow.isPending ? 'Tracing…' : 'Trace Flow'}
            </button>
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

      {mode === 'flow' && flow.isError && (
        <div className="architecture-banner">{errorMessage(flow.error)}</div>
      )}
      {mode === 'flow' && flow.data?.message && <div className="architecture-banner">{flow.data.message}</div>}
      {mode === 'flow' && !flow.data && !flow.isPending && !flow.isError && (
        <div className="architecture-banner">
          Select a file in the file tree (or describe a feature above) and click &ldquo;Trace Flow&rdquo;.
        </div>
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

function FileInspector({ filePath, data }) {
  const functions = data.symbols.filter((symbol) => symbol.kind === 'function' && symbol.file === filePath)
  const classes = data.symbols.filter((symbol) => symbol.kind === 'class' && symbol.file === filePath)
  const imports = data.imports.filter((entry) => entry.file === filePath)
  const exports = data.exports.filter((entry) => entry.file === filePath)
  const relationships = data.relationships.filter(
    (rel) => rel.source === filePath || rel.source.startsWith(`${filePath}::`),
  )

  return (
    <div className="file-inspector">
      <section>
        <h3 className="panel-title">Functions</h3>
        {functions.length > 0 ? (
          <ul className="inspector-list">
            {functions.map((fn) => (
              <li key={`${fn.name}-${fn.start_line}`}>
                {fn.name}
                {fn.is_method && fn.class_name ? ` (${fn.class_name})` : ''}
              </li>
            ))}
          </ul>
        ) : (
          <p className="card-subtitle">None found.</p>
        )}
      </section>

      <section>
        <h3 className="panel-title">Classes</h3>
        {classes.length > 0 ? (
          <ul className="inspector-list">
            {classes.map((cls) => (
              <li key={cls.name}>
                {cls.name}
                {cls.methods.length > 0 ? ` — ${cls.methods.join(', ')}` : ''}
              </li>
            ))}
          </ul>
        ) : (
          <p className="card-subtitle">None found.</p>
        )}
      </section>

      <section>
        <h3 className="panel-title">Imports</h3>
        {imports.length > 0 ? (
          <ul className="inspector-list">
            {imports.map((imp, index) => (
              <li key={`${imp.source}-${index}`}>
                {imp.source}
                {imp.is_external ? ' (external)' : imp.resolved_target ? ` → ${imp.resolved_target}` : ' (unresolved)'}
              </li>
            ))}
          </ul>
        ) : (
          <p className="card-subtitle">None found.</p>
        )}
      </section>

      <section>
        <h3 className="panel-title">Exports</h3>
        {exports.length > 0 ? (
          <ul className="inspector-list">
            {exports.map((exp, index) => (
              <li key={`${exp.name}-${index}`}>
                {exp.name} ({exp.kind})
              </li>
            ))}
          </ul>
        ) : (
          <p className="card-subtitle">None found.</p>
        )}
      </section>

      <section>
        <h3 className="panel-title">Relationships</h3>
        {relationships.length > 0 ? (
          <ul className="inspector-list">
            {relationships.map((rel, index) => (
              <li key={index}>
                {rel.type}
                {rel.target ? ` → ${rel.target}` : rel.raw_callee ? ` → ${rel.raw_callee} (unresolved)` : ''}
              </li>
            ))}
          </ul>
        ) : (
          <p className="card-subtitle">None found.</p>
        )}
      </section>
    </div>
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

function CodeIntelligenceTab() {
  const [selectedFile, setSelectedFile] = useState('')
  const queryClient = useQueryClient()
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['code-intelligence'],
    queryFn: fetchCodeIntelligence,
    retry: false,
  })
  const runAnalysis = useMutation({
    mutationFn: runCodeAnalysis,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['code-intelligence'] }),
  })

  function handleRun() {
    runAnalysis.mutate(undefined, {
      onSuccess: () => toast.success('Code intelligence analysis complete'),
      onError: (err) => {
        const message = err instanceof ApiError ? err.message : 'Something went wrong. Please try again.'
        toast.error('Analysis failed', { description: message })
      },
    })
  }

  const notAnalyzedYet = isError && error instanceof ApiError && error.status === 404

  return (
    <>
      <div className="button-row mb-6">
        <button className="btn btn-primary" onClick={handleRun} disabled={runAnalysis.isPending}>
          {runAnalysis.isPending ? 'Running…' : 'Run Analysis'}
        </button>
      </div>

      {isPending && (
        <div className="panel">
          <p className="card-subtitle">Loading…</p>
        </div>
      )}

      {notAnalyzedYet && (
        <div className="panel">
          <h2 className="panel-title">No analysis yet</h2>
          <p className="card-subtitle">Click &ldquo;Run Analysis&rdquo; to parse this repository with Tree-sitter.</p>
        </div>
      )}

      {isError && !notAnalyzedYet && (
        <div className="panel">
          <h2 className="panel-title">Could not load analysis</h2>
          <p className="card-subtitle">{error.message}</p>
        </div>
      )}

      {data && (
        <>
          <div className="stat-grid">
            <div className="panel">
              <p className="stat-label">Files parsed</p>
              <p className="stat-value">{data.stats.files_parsed}</p>
            </div>
            <div className="panel">
              <p className="stat-label">Functions</p>
              <p className="stat-value">{data.symbols.filter((s) => s.kind === 'function').length}</p>
            </div>
            <div className="panel">
              <p className="stat-label">Classes</p>
              <p className="stat-value">{data.symbols.filter((s) => s.kind === 'class').length}</p>
            </div>
            <div className="panel">
              <p className="stat-label">Imports</p>
              <p className="stat-value">{data.imports.length}</p>
            </div>
            <div className="panel">
              <p className="stat-label">Relationships</p>
              <p className="stat-value">{data.relationships.length}</p>
            </div>
            <div className="panel">
              <p className="stat-label">Routes</p>
              <p className="stat-value">{data.routes.length}</p>
            </div>
          </div>

          <div className="panel">
            <h2 className="panel-title">Inspect a file</h2>
            <select className="select" value={selectedFile} onChange={(event) => setSelectedFile(event.target.value)}>
              <option value="">Select a file…</option>
              {data.files.map((file) => (
                <option key={file.path} value={file.path}>
                  {file.path}
                </option>
              ))}
            </select>

            {selectedFile && <FileInspector filePath={selectedFile} data={data} />}
          </div>
        </>
      )}
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
            <div className="panel">
              <p className="card-subtitle">Analyzing repository…</p>
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
              <h1 className="card-title">Could not load analysis</h1>
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
                className={tab === 'code-intelligence' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                onClick={() => setTab('code-intelligence')}
              >
                Code Intelligence (Debug)
              </button>
            </div>

            {tab === 'overview' && <OverviewTab data={data} />}
            {tab === 'architecture' && <ArchitectureTab />}
            {tab === 'code-intelligence' && <CodeIntelligenceTab />}
          </div>
        </main>
      </div>
    </div>
  )
}
