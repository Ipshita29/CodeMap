import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster as Sonner } from 'sonner'

import { ErrorBoundary } from '@/ErrorBoundary'
import { LandingPage } from '@/pages/landing'
import { AnalyzingPage } from '@/pages/analyzing'
import { WorkspacePage } from '@/pages/workspace'

const queryClient = new QueryClient()

function App() {
  const [view, setView] = useState('landing')
  const [repositoryName, setRepositoryName] = useState(null)

  function handleImportAnother() {
    queryClient.clear()
    setRepositoryName(null)
    setView('landing')
  }

  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary key={view} label="CodeMap">
        {view === 'landing' && (
          <LandingPage
            onImported={(name) => {
              setRepositoryName(name)
              setView('analyzing')
            }}
          />
        )}
        {view === 'analyzing' && (
          <AnalyzingPage repositoryName={repositoryName} onReady={() => setView('workspace')} onBack={handleImportAnother} />
        )}
        {view === 'workspace' && <WorkspacePage repositoryId={repositoryName} onImportAnother={handleImportAnother} />}
      </ErrorBoundary>
      <Sonner
        theme="dark"
        position="top-right"
        style={{
          '--normal-bg': 'var(--card)',
          '--normal-text': 'var(--foreground)',
          '--normal-border': 'var(--card-border)',
        }}
      />
    </QueryClientProvider>
  )
}

export default App
