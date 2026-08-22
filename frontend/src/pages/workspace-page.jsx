import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { AppShell } from '@/components/layout/AppShell'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { RepositoryOverview } from '@/components/repository/RepositoryOverview'
import { ArchitectureWorkspace } from '@/components/architecture/ArchitectureWorkspace'
import { GitHistory } from '@/components/git/GitHistory'
import { HealthDashboard } from '@/components/health/HealthDashboard'
import { fetchRepositoryAnalysis } from '@/api'

export function WorkspacePage({ onImportAnother }) {
  const [section, setSection] = useState('overview')
  // { question, key } handed to the Overview's Ask CodeMap panel -- `key`
  // (not just the question text) is what the panel keys its focus/prefill
  // effect off of, so asking the same contextual question twice in a row
  // still re-focuses it. Ask CodeMap has exactly one home now (the Overview
  // hero card); this is how Architecture/Git/Health reach it without each
  // duplicating their own "Ask CodeMap" entry point.
  const [askPrefill, setAskPrefill] = useState(null)
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['repository-analysis'],
    queryFn: fetchRepositoryAnalysis,
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
    <AppShell
      sidebar={<Sidebar activeSection={section} onSectionChange={setSection} repositoryName={data.repository_name} />}
      topbar={<TopBar repositoryAnalysis={data} onImportAnother={onImportAnother} />}
    >
      {section === 'overview' && (
        <RepositoryOverview data={data} onExploreStructure={() => setSection('architecture')} askPrefill={askPrefill} />
      )}
      {section === 'architecture' && <ArchitectureWorkspace onAskAbout={askAbout} />}
      {section === 'git' && <GitHistory onAskAbout={askAbout} />}
      {section === 'health' && <HealthDashboard onAskAbout={askAbout} />}
    </AppShell>
  )
}
