import { MainLayout } from '@/layouts/main-layout'
import { RepositoryImportForm } from '@/components/repository-import-form'

export function LandingPage() {
  return (
    <MainLayout>
      <RepositoryImportForm />
    </MainLayout>
  )
}
