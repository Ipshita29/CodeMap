export function AppShell({ sidebar, topbar, children }) {
  return (
    <div className="workspace-shell">
      {sidebar}
      <div className="workspace-body">
        {topbar}
        <main className="workspace-main">
          <div className="workspace-content">{children}</div>
        </main>
      </div>
    </div>
  )
}
