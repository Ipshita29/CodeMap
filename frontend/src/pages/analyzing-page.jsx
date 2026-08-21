import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'

import { AnalysisProgress } from '@/components/repository/AnalysisProgress'
import { fetchRepositoryAnalysis } from '@/api'

export function AnalyzingPage({ repositoryName, onReady, onBack }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['repository-analysis'],
    queryFn: fetchRepositoryAnalysis,
  })

  useEffect(() => {
    if (data) onReady()
  }, [data, onReady])

  return (
    <div className="app-shell">
      <div className="app-glow" />
      <div className="app-content">
        <header className="app-header">
          <div className="logo-mark">C</div>
          <span className="logo-text">CodeMap</span>
        </header>
        <main className="app-main">
          {isError ? (
            <div className="panel">
              <h1 className="card-title">Repository could not be analyzed</h1>
              <p className="card-subtitle">{error.message}</p>
              <button className="btn btn-outline btn-block mt-6" onClick={onBack}>
                Back
              </button>
            </div>
          ) : (
            <AnalysisProgress repositoryName={repositoryName} fileCount={data?.total_files} indexed={!isPending} />
          )}
        </main>
      </div>
    </div>
  )
}
