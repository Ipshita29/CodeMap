import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { Toaster } from '@/components/ui/sonner'
import { LandingPage } from '@/pages/landing-page'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <LandingPage />
      <Toaster position="top-right" />
    </QueryClientProvider>
  )
}

export default App
