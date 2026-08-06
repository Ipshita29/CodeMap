import { MainLayout } from '@/layouts/main-layout'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { FolderTreeView } from '@/components/folder-tree-view'
import { useRepositoryAnalysis } from '@/hooks/use-repository-analysis'

export function AnalysisPage({ onBack }) {
  const { data, isPending, isError, error } = useRepositoryAnalysis()

  if (isPending) {
    return (
      <MainLayout>
        <Panel>
          <p className="card-subtitle">Analyzing repository…</p>
        </Panel>
      </MainLayout>
    )
  }

  if (isError) {
    return (
      <MainLayout>
        <Panel>
          <h1 className="card-title">Could not load analysis</h1>
          <p className="card-subtitle">{error.message}</p>
          <Button variant="outline" block className="mt-6" onClick={onBack}>
            Back
          </Button>
        </Panel>
      </MainLayout>
    )
  }

  const { repository_name, total_files, total_folders, languages, frameworks, folder_tree, statistics } = data
  const hasFolders = Object.keys(folder_tree).length > 0

  return (
    <MainLayout>
      <div className="analysis-page">
        <div className="analysis-header">
          <div>
            <h1 className="card-title">{repository_name}</h1>
            <p className="card-subtitle">Repository analysis</p>
          </div>
          <Button variant="outline" onClick={onBack}>
            Import another repository
          </Button>
        </div>

        <div className="stat-grid">
          <Panel>
            <p className="stat-label">Total files</p>
            <p className="stat-value">{total_files}</p>
          </Panel>
          <Panel>
            <p className="stat-label">Total folders</p>
            <p className="stat-value">{total_folders}</p>
          </Panel>
          <Panel>
            <p className="stat-label">Total lines</p>
            <p className="stat-value">{statistics.total_lines}</p>
          </Panel>
          <Panel>
            <p className="stat-label">Largest file</p>
            <p className="stat-value stat-value-small">
              {statistics.largest_file ? statistics.largest_file.path : '—'}
            </p>
          </Panel>
        </div>

        <div className="analysis-columns">
          <Panel>
            <h2 className="panel-title">Languages</h2>
            {Object.keys(languages).length > 0 ? (
              <ul className="tag-list">
                {Object.entries(languages).map(([language, count]) => (
                  <li key={language} className="tag">
                    {language}
                    <span className="tag-count">{count}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="card-subtitle">No recognized languages found.</p>
            )}
          </Panel>

          <Panel>
            <h2 className="panel-title">Frameworks</h2>
            {frameworks.length > 0 ? (
              <ul className="tag-list">
                {frameworks.map((framework) => (
                  <li key={framework} className="tag">
                    {framework}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="card-subtitle">No frameworks detected.</p>
            )}
          </Panel>
        </div>

        <Panel>
          <h2 className="panel-title">Folder structure</h2>
          {hasFolders ? (
            <FolderTreeView tree={folder_tree} />
          ) : (
            <p className="card-subtitle">No subfolders found.</p>
          )}
        </Panel>
      </div>
    </MainLayout>
  )
}
