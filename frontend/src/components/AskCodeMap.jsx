import { X } from 'lucide-react'

import { AskCodeMapPanel } from '@/components/AskCodeMapPanel'

export function AskCodeMap({ data, onClose }) {
  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="drawer-panel">
        <div className="drawer-header">
          <h2>Ask CodeMap</h2>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="drawer-body">
          <p className="card-subtitle">Ask anything about this repository.</p>
          <AskCodeMapPanel data={data} autoFocus />
        </div>
      </aside>
    </>
  )
}
