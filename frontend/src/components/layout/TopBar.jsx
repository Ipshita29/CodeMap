import { ExportMenu } from '@/components/export/ExportMenu'

export function TopBar({ repositoryAnalysis, onImportAnother }) {
  return (
    <header className="workspace-topbar">
      <div>
        <h1 className="workspace-topbar-title">{repositoryAnalysis.repository_name}</h1>
        <p className="workspace-topbar-subtitle">Repository analysis</p>
      </div>
      <div className="workspace-topbar-actions">
        <ExportMenu repositoryAnalysis={repositoryAnalysis} />
        <button type="button" className="btn btn-outline" onClick={onImportAnother}>
          Import repository
        </button>
      </div>
    </header>
  )
}
