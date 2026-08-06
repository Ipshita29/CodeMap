export function FolderTreeView({ tree }) {
  const entries = Object.entries(tree)

  if (entries.length === 0) return null

  return (
    <ul className="folder-tree">
      {entries.map(([name, children]) => (
        <li key={name}>
          <span className="folder-tree-name">{name}</span>
          <FolderTreeView tree={children} />
        </li>
      ))}
    </ul>
  )
}
