import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError, askRepositoryQuestion } from '@/api'

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

const SUGGESTED_QUESTIONS = [
  'Explain the architecture',
  'Find the main entry point',
  'What are the biggest risks?',
  'How does X depend on Y?',
]

function SourcesList({ sources }) {
  if (sources.length === 0) return null
  return (
    <div className="sources">
      <p className="sources-title">Sources</p>
      <ul className="sources-list">
        {sources.map((source) => (
          <li key={source}>
            <button
              type="button"
              className="source-link"
              onClick={() => toast('File viewer is coming in a future update', { description: source })}
            >
              {source}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function AskCodeMap({ onClose }) {
  const [mode, setMode] = useState('developer')
  const [question, setQuestion] = useState('')
  const [conversation, setConversation] = useState([])
  const chat = useMutation({ mutationFn: askRepositoryQuestion })

  function handleAsk(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || chat.isPending) return

    chat.mutate(
      { question: trimmed, mode },
      {
        onSuccess: (data) => {
          setConversation((prev) => [{ question: trimmed, ...data }, ...prev])
          setQuestion('')
        },
        onError: (error) => toast.error('Could not get an answer', { description: errorMessage(error) }),
      },
    )
  }

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

          <div className="mode-toggle">
            <button
              type="button"
              className={mode === 'beginner' ? 'mode-btn mode-btn-active' : 'mode-btn'}
              onClick={() => setMode('beginner')}
            >
              Beginner
            </button>
            <button
              type="button"
              className={mode === 'developer' ? 'mode-btn mode-btn-active' : 'mode-btn'}
              onClick={() => setMode('developer')}
            >
              Developer
            </button>
          </div>

          <form onSubmit={handleAsk} className="import-form">
            <input
              className="input"
              type="text"
              placeholder="How does authentication work?"
              value={question}
              disabled={chat.isPending}
              onChange={(event) => setQuestion(event.target.value)}
              autoFocus
            />
            <button type="submit" className="btn btn-primary" disabled={chat.isPending || !question.trim()}>
              {chat.isPending ? 'Thinking…' : 'Ask'}
            </button>
          </form>

          {conversation.length === 0 && (
            <div className="suggested-questions">
              <p className="sources-title">Suggested questions</p>
              {SUGGESTED_QUESTIONS.map((suggested) => (
                <button
                  key={suggested}
                  type="button"
                  className="suggested-question"
                  onClick={() => setQuestion(suggested)}
                >
                  {suggested}
                </button>
              ))}
            </div>
          )}

          {conversation.length > 0 && (
            <div className="conversation-list">
              {conversation.map((entry, index) => (
                <div className="conversation-entry" key={`${entry.question}-${index}`}>
                  <p className="conversation-question">{entry.question}</p>
                  <p className="conversation-answer">{entry.answer}</p>
                  <SourcesList sources={entry.sources} />
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </>
  )
}
