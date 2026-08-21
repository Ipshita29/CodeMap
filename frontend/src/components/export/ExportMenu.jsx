import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError, exportPdf, fetchRepositoryGraph } from '@/api'
import { buildJsonExport, buildMarkdownReport, downloadBlob, downloadTextFile } from '@/lib/build-report'

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

// Deliberately reads the query cache passively instead of fetching --
// export should only ever include what's already been analyzed in this
// session (visiting Architecture/Git/Health), never trigger new background
// work just because the menu was opened.
export function ExportMenu({ repositoryAnalysis }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)
  const queryClient = useQueryClient()
  const pdfExport = useMutation({ mutationFn: exportPdf })

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
      graph = await fetchRepositoryGraph({})
    } catch {
      graph = null // JSON export still works without the graph -- it's supplementary
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
      <button type="button" className="btn btn-outline" onClick={() => setOpen((prev) => !prev)} aria-label="Export">
        <MoreHorizontal size={16} />
      </button>

      {open && (
        <div className="dropdown-panel">
          <p className="dropdown-label">Export</p>
          <button type="button" className="dropdown-item" onClick={handleDownloadMarkdown}>
            Download Markdown
          </button>
          <button type="button" className="dropdown-item" onClick={handleDownloadJson}>
            Download JSON
          </button>
          <button type="button" className="dropdown-item" onClick={handleDownloadPdf} disabled={pdfExport.isPending}>
            {pdfExport.isPending ? 'Generating PDF…' : 'Download PDF'}
          </button>
          <div className="dropdown-divider" />
          <p className="dropdown-label">Share</p>
          <button type="button" className="dropdown-item" onClick={handleCopyMarkdown}>
            Copy Markdown to Clipboard
          </button>
        </div>
      )}
    </div>
  )
}
