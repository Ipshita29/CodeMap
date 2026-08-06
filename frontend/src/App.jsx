import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { Toaster } from '@/components/ui/sonner'
import { LandingPage } from '@/pages/landing-page'
import { AnalysisPage } from '@/pages/analysis-page'

const queryClient = new QueryClient()

function App() {
  const [view, setView] = useState('landing')

  return (
    <QueryClientProvider client={queryClient}>
      {view === 'landing' ? (
        <LandingPage onViewAnalysis={() => setView('analysis')} />
      ) : (
        <AnalysisPage onBack={() => setView('landing')} />
      )}
      <Toaster position="top-right" />
    </QueryClientProvider>
  )
}

export default App
