import { MainLayout } from '@/layouts/main-layout'
import { RepositoryImportForm } from '@/components/repository-import-form'

export function LandingPage({ onViewAnalysis }) {
  return (
    <MainLayout>
      <RepositoryImportForm onViewAnalysis={onViewAnalysis} />
    </MainLayout>
  )
}
