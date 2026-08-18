import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { AppShell } from '@/components/AppShell'
import { Sidebar } from '@/components/Sidebar'
import { TopBar } from '@/components/TopBar'
import { AskCodeMap } from '@/components/AskCodeMap'
import { RepositoryOverview } from '@/components/RepositoryOverview'
import { ArchitectureWorkspace } from '@/components/ArchitectureWorkspace'
import { GitHistory } from '@/components/GitHistory'
import { HealthDashboard } from '@/components/HealthDashboard'
import { fetchRepositoryAnalysis } from '@/api'

export function WorkspacePage({ onImportAnother }) {
  const [section, setSection] = useState('overview')
  const [askOpen, setAskOpen] = useState(false)
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['repository-analysis'],
    queryFn: fetchRepositoryAnalysis,
  })

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
    <>
      <AppShell
        sidebar={<Sidebar activeSection={section} onSectionChange={setSection} onAskCodeMap={() => setAskOpen(true)} />}
        topbar={
          <TopBar repositoryAnalysis={data} onAskCodeMap={() => setAskOpen(true)} onImportAnother={onImportAnother} />
        }
      >
        {section === 'overview' && (
          <RepositoryOverview data={data} onExploreStructure={() => setSection('architecture')} />
        )}
        {section === 'architecture' && <ArchitectureWorkspace />}
        {section === 'git' && <GitHistory />}
        {section === 'health' && <HealthDashboard />}
      </AppShell>

      {askOpen && <AskCodeMap data={data} onClose={() => setAskOpen(false)} />}
    </>
  )
}
