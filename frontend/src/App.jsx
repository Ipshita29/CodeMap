import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster as Sonner } from 'sonner'

import { LandingPage } from '@/pages/landing-page'
import { AnalysisPage } from '@/pages/analysis-page'
import { RepositoryInsightsPage } from '@/pages/repository-insights-page'

const queryClient = new QueryClient()

function App() {
  const [view, setView] = useState('landing')

  return (
    <QueryClientProvider client={queryClient}>
      {view === 'landing' && <LandingPage onViewAnalysis={() => setView('analysis')} />}
      {view === 'analysis' && (
        <AnalysisPage onBack={() => setView('landing')} onViewInsights={() => setView('insights')} />
      )}
      {view === 'insights' && <RepositoryInsightsPage onBack={() => setView('analysis')} />}
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
