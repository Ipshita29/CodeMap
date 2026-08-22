import { Activity, GitBranch, LayoutGrid, Network } from 'lucide-react'

// Repository destinations only -- Ask CodeMap isn't one of these anymore.
// It lives exclusively as the hero card on Overview (see
// components/ai/AskCodeMapPanel.jsx); Architecture/Git/Health reach it via
// small contextual actions rather than a sidebar entry of its own.
const NAV_TILES = [
  { id: 'overview', label: 'Overview', icon: LayoutGrid, accent: 'teal' },
  { id: 'architecture', label: 'Architecture', icon: Network, accent: 'blue' },
  { id: 'git', label: 'Git History', icon: GitBranch, accent: 'amber' },
  { id: 'health', label: 'Health', icon: Activity, accent: 'green' },
]

export function Sidebar({ activeSection, onSectionChange, repositoryName }) {
  return (
    <aside className="workspace-sidebar">
      <div className="workspace-brand">
        <div className="logo-mark">C</div>
        <span className="logo-text">CodeMap</span>
      </div>

      <nav className="sidebar-nav">
        <p className="sidebar-group-label">Repository</p>
        <div className="sidebar-tiles">
          {NAV_TILES.map((tile) => {
            const isActive = activeSection === tile.id
            return (
              <button
                key={tile.id}
                type="button"
                className={`sidebar-tile sidebar-tile-${tile.accent}${isActive ? ' sidebar-tile-active' : ''}`}
                onClick={() => onSectionChange(tile.id)}
                aria-current={isActive ? 'page' : undefined}
              >
                <span className="sidebar-tile-icon">
                  <tile.icon size={17} />
                </span>
                <span className="sidebar-tile-text">
                  <span className="sidebar-tile-label">{tile.label}</span>
                </span>
              </button>
            )
          })}
        </div>
      </nav>

      <div className="sidebar-spacer" />

      {repositoryName && (
        <div className="sidebar-footer">
          <div className="sidebar-repo">
            <span className="sidebar-repo-text">
              <span className="sidebar-repo-name">{repositoryName}</span>
              <span className="sidebar-repo-label">Repository</span>
            </span>
            <span className="sidebar-repo-dot" aria-hidden="true" />
          </div>
        </div>
      )}
    </aside>
  )
}
