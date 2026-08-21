import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError, askRepositoryQuestion } from '@/api'
import { buildSuggestedQuestions } from '@/lib/repository-intelligence'

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

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

// Shared by the Overview hero section and the sidebar drawer -- one piece
// of chat logic, two places it's displayed, per "don't duplicate AI logic."
export function AskCodeMapPanel({ data, autoFocus = false, suggestionsLabel = 'Suggested questions' }) {
  const [question, setQuestion] = useState('')
  const [conversation, setConversation] = useState([])
  const chat = useMutation({ mutationFn: askRepositoryQuestion })
  const queryClient = useQueryClient()

  const codeIntelligence = queryClient.getQueryData(['code-intelligence'])
  const suggestions = buildSuggestedQuestions(data, codeIntelligence)

  function handleAsk(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || chat.isPending) return

    chat.mutate(
      { question: trimmed, mode: 'developer' },
      {
        onSuccess: (result) => {
          setConversation((prev) => [{ question: trimmed, ...result }, ...prev])
          setQuestion('')
        },
        onError: (error) => toast.error('Could not get an answer', { description: errorMessage(error) }),
      },
    )
  }

  return (
    <>
      <form onSubmit={handleAsk} className="ask-codemap-form">
        <input
          className="input ask-codemap-input"
          type="text"
          placeholder="Ask anything about this codebase…"
          value={question}
          disabled={chat.isPending}
          onChange={(event) => setQuestion(event.target.value)}
          autoFocus={autoFocus}
        />
        <button type="submit" className="btn btn-primary" disabled={chat.isPending || !question.trim()}>
          {chat.isPending ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      {conversation.length === 0 && (
        <div className="suggested-questions">
          <p className="sources-title">{suggestionsLabel}</p>
          <div className="suggested-question-grid">
            {suggestions.map((suggested) => (
              <button key={suggested} type="button" className="suggested-question" onClick={() => setQuestion(suggested)}>
                {suggested}
              </button>
            ))}
          </div>
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
    </>
  )
}

// The sidebar/topbar entry point into Ask CodeMap -- drawer chrome around
// the same panel used inline on Overview.
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
