import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, GitBranch, LayoutGrid, Loader2, MoreHorizontal, Network } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError, exportPdf, fetchRepositoryAnalysis, fetchRepositoryGraph } from '@/api'
import { buildJsonExport, buildMarkdownReport, downloadBlob, downloadTextFile } from '@/build-report'
import { ErrorBoundary } from '@/ErrorBoundary'
import { useDismissableOverlay } from '@/hooks/useDismissableOverlay'
import { RepositoryOverview } from './overview'
import '../css/workspace.css'

// Code-split: Architecture pulls in @xyflow/react + @dagrejs/dagre, and
// none of the three sections below are needed for the initial Overview
// experience -- each only downloads once the user actually opens it. The
// `.then` unwrap is because these pages use named exports (kept as-is
// everywhere else), while React.lazy requires a default export.
const ArchitectureWorkspace = lazy(() =>
  import('./architecture').then((module) => ({ default: module.ArchitectureWorkspace })),
)
const GitHistory = lazy(() => import('./githistory').then((module) => ({ default: module.GitHistory })))
const HealthDashboard = lazy(() => import('./health').then((module) => ({ default: module.HealthDashboard })))

function SectionLoadingFallback() {
  return (
    <div className="panel error-boundary-panel">
      <p className="card-subtitle">
        <Loader2 className="spinner" size={16} /> Loading…
      </p>
    </div>
  )
}

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

const NAV_TILES = [
  { id: 'overview', label: 'Overview', icon: LayoutGrid, accent: 'teal' },
  { id: 'architecture', label: 'Architecture', icon: Network, accent: 'blue' },
  { id: 'git', label: 'Git History', icon: GitBranch, accent: 'amber' },
  { id: 'health', label: 'Health', icon: Activity, accent: 'green' },
]

function Sidebar({ activeSection, onSectionChange, repositoryName }) {
  return (
    <aside className="workspace-sidebar">
      <div className="workspace-brand">
        <div className="logo-mark">C</div>
        <span className="logo-text">CodeMap</span>
      </div>

      <nav className="sidebar-nav">
        <p className="sidebar-group-label">Repository</p>
        <div className="sidebar-tiles">
          {NAV_TILES.map((tile) => {
            const isActive = activeSection === tile.id
            return (
              <button
                key={tile.id}
                type="button"
                className={`sidebar-tile sidebar-tile-${tile.accent}${isActive ? ' sidebar-tile-active' : ''}`}
                onClick={() => onSectionChange(tile.id)}
                aria-current={isActive ? 'page' : undefined}
              >
                <span className="sidebar-tile-icon">
                  <tile.icon size={17} />
                </span>
                <span className="sidebar-tile-text">
                  <span className="sidebar-tile-label">{tile.label}</span>
                </span>
              </button>
            )
          })}
        </div>
      </nav>

      <div className="sidebar-spacer" />

      {repositoryName && (
        <div className="sidebar-footer">
          <div className="sidebar-repo">
            <span className="sidebar-repo-text">
              <span className="sidebar-repo-name">{repositoryName}</span>
              <span className="sidebar-repo-label">Repository</span>
            </span>
            <span className="sidebar-repo-dot" aria-hidden="true" />
          </div>
        </div>
      )}
    </aside>
  )
}
function ExportMenu({ repositoryId, repositoryAnalysis }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)
  const queryClient = useQueryClient()
  const pdfExport = useMutation({ mutationFn: exportPdf })
  // Escape, Tab-trapping while open, and returning focus to the trigger on
  // close -- attached to the panel itself (not containerRef below, which
  // also wraps the trigger button and exists purely for the separate
  // click-outside check).
  const panelRef = useDismissableOverlay(open, () => setOpen(false))

  useEffect(() => {
    if (!open) return
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  function collectData() {
    const summary = queryClient.getQueryData(['repository-summary'])
    return {
      repositoryAnalysis,
      codeIntelligence: queryClient.getQueryData(['code-intelligence']) ?? null,
      health: queryClient.getQueryData(['repository-health']) ?? null,
      gitSummary: queryClient.getQueryData(['git-summary']) ?? null,
      beginnerSummary: summary?.beginner_summary ?? null,
      developerSummary: summary?.developer_summary ?? null,
      lastImpact: queryClient.getQueryData(['last-impact-result']) ?? null,
    }
  }

  function handleDownloadMarkdown() {
    const markdown = buildMarkdownReport(collectData())
    downloadTextFile(`codemap-${repositoryAnalysis.repository_name}.md`, markdown, 'text/markdown')
    setOpen(false)
  }

  async function handleDownloadJson() {
    let graph = null
    try {
      graph = await fetchRepositoryGraph(repositoryId, {})
    } catch {
      graph = null 
    }
    const json = buildJsonExport({ ...collectData(), graph })
    downloadTextFile(`codemap-${repositoryAnalysis.repository_name}.json`, JSON.stringify(json, null, 2), 'application/json')
    setOpen(false)
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
    setOpen(false)
  }

  async function handleCopyMarkdown() {
    const markdown = buildMarkdownReport(collectData())
    try {
      await navigator.clipboard.writeText(markdown)
      toast.success('Markdown report copied to clipboard')
    } catch {
      toast.error('Could not copy to clipboard')
    }
    setOpen(false)
  }

  return (
    <div className="dropdown" ref={containerRef}>
      <button
        type="button"
        className="btn btn-outline"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Export"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <MoreHorizontal size={16} />
      </button>

      {open && (
        <div className="dropdown-panel" ref={panelRef} role="menu">
          <p className="dropdown-label">Export</p>
          <button type="button" role="menuitem" className="dropdown-item" onClick={handleDownloadMarkdown}>
            Download Markdown
          </button>
          <button type="button" role="menuitem" className="dropdown-item" onClick={handleDownloadJson}>
            Download JSON
          </button>
          <button
            type="button"
            role="menuitem"
            className="dropdown-item"
            onClick={handleDownloadPdf}
            disabled={pdfExport.isPending}
          >
            {pdfExport.isPending ? 'Generating PDF…' : 'Download PDF'}
          </button>
          <div className="dropdown-divider" />
          <p className="dropdown-label">Share</p>
          <button type="button" role="menuitem" className="dropdown-item" onClick={handleCopyMarkdown}>
            Copy Markdown to Clipboard
          </button>
        </div>
      )}
    </div>
  )
}

function TopBar({ repositoryId, repositoryAnalysis, onImportAnother }) {
  return (
    <header className="workspace-topbar">
      <div>
        <h1 className="workspace-topbar-title">{repositoryAnalysis.repository_name}</h1>
        <p className="workspace-topbar-subtitle">Repository analysis</p>
      </div>
      <div className="workspace-topbar-actions">
        <ExportMenu repositoryId={repositoryId} repositoryAnalysis={repositoryAnalysis} />
        <button type="button" className="btn btn-outline" onClick={onImportAnother}>
          Import repository
        </button>
      </div>
    </header>
  )
}

export function WorkspacePage({ repositoryId, onImportAnother }) {
  const [section, setSection] = useState('overview')
  const [askPrefill, setAskPrefill] = useState(null)
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['repository-analysis'],
    queryFn: () => fetchRepositoryAnalysis(repositoryId),
  })

  function askAbout(question) {
    setAskPrefill({ question, key: Date.now() })
    setSection('overview')
  }

  if (isPending || isError) {
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
              {isError ? (
                <>
                  <h1 className="card-title">Repository could not be analyzed</h1>
                  <p className="card-subtitle">{error.message}</p>
                  <button className="btn btn-outline btn-block mt-6" onClick={onImportAnother}>
                    Back
                  </button>
                </>
              ) : (
                <p className="card-subtitle">Loading…</p>
              )}
            </div>
          </main>
        </div>
      </div>
    )
  }

  return (
    <div className="workspace-shell">
      <Sidebar activeSection={section} onSectionChange={setSection} repositoryName={data.repository_name} />
      <div className="workspace-body">
        <TopBar repositoryId={repositoryId} repositoryAnalysis={data} onImportAnother={onImportAnother} />
        <main className="workspace-main">
          <div className="workspace-content">
            {section === 'overview' && (
              <ErrorBoundary label="the Overview section">
                <RepositoryOverview
                  repositoryId={repositoryId}
                  data={data}
                  onExploreStructure={() => setSection('architecture')}
                  askPrefill={askPrefill}
                />
              </ErrorBoundary>
            )}
            {section === 'architecture' && (
              <ErrorBoundary label="the Architecture section">
                <Suspense fallback={<SectionLoadingFallback />}>
                  <ArchitectureWorkspace repositoryId={repositoryId} onAskAbout={askAbout} />
                </Suspense>
              </ErrorBoundary>
            )}
            {section === 'git' && (
              <ErrorBoundary label="the Git History section">
                <Suspense fallback={<SectionLoadingFallback />}>
                  <GitHistory repositoryId={repositoryId} onAskAbout={askAbout} />
                </Suspense>
              </ErrorBoundary>
            )}
            {section === 'health' && (
              <ErrorBoundary label="the Health section">
                <Suspense fallback={<SectionLoadingFallback />}>
                  <HealthDashboard repositoryId={repositoryId} onAskAbout={askAbout} />
                </Suspense>
              </ErrorBoundary>
            )}
          </div>
        </main>
      </div>
    </div>
  )
}
