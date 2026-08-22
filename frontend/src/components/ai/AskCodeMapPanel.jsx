import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
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

// The single Ask CodeMap experience -- lives inline on Overview. `prefill`
// (an object `{ question, key }`) is how other pages hand it a
// context-specific question: bump `key` to force the effect even if the
// question text repeats, since a plain string wouldn't re-trigger.
export function AskCodeMapPanel({ data, autoFocus = false, suggestionsLabel = 'Suggested questions', prefill }) {
  const [question, setQuestion] = useState('')
  const [conversation, setConversation] = useState([])
  const chat = useMutation({ mutationFn: askRepositoryQuestion })
  const queryClient = useQueryClient()
  const inputRef = useRef(null)

  const codeIntelligence = queryClient.getQueryData(['code-intelligence'])
  const suggestions = buildSuggestedQuestions(data, codeIntelligence)

  useEffect(() => {
    if (!prefill) return
    setQuestion(prefill.question)
    inputRef.current?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.key])

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
          ref={inputRef}
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
