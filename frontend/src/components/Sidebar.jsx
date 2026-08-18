import { Activity, Compass, GitBranch, Network, Sparkles } from 'lucide-react'

const REPOSITORY_LINKS = [
  { id: 'overview', label: 'Overview', icon: Compass },
  { id: 'architecture', label: 'Architecture', icon: Network },
  { id: 'git', label: 'Git History', icon: GitBranch },
  { id: 'health', label: 'Health', icon: Activity },
]

export function Sidebar({ activeSection, onSectionChange, onAskCodeMap }) {
  return (
    <aside className="workspace-sidebar">
      <div className="workspace-brand">
        <div className="logo-mark">C</div>
        <span className="logo-text">CodeMap</span>
      </div>

      <nav className="sidebar-nav">
        <div className="sidebar-nav-group">
          <p className="sidebar-group-label">Repository</p>
          {REPOSITORY_LINKS.map((link) => (
            <button
              key={link.id}
              type="button"
              className={`sidebar-link${activeSection === link.id ? ' sidebar-link-active' : ''}`}
              onClick={() => onSectionChange(link.id)}
            >
              <link.icon className="sidebar-link-icon" size={16} />
              {link.label}
            </button>
          ))}
        </div>

        <div className="sidebar-nav-group">
          <p className="sidebar-group-label">AI</p>
          <button type="button" className="sidebar-link" onClick={onAskCodeMap}>
            <Sparkles className="sidebar-link-icon" size={16} />
            Ask CodeMap
          </button>
        </div>
      </nav>

      <div className="sidebar-spacer" />
    </aside>
  )
}
