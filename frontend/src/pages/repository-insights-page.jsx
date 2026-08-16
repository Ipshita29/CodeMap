import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError, askRepositoryQuestion, generateRepositorySummary } from '@/api'

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

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

export function RepositoryInsightsPage({ onBack }) {
  const [mode, setMode] = useState('beginner')
  const [question, setQuestion] = useState('')
  const [conversation, setConversation] = useState([])

  const summary = useMutation({ mutationFn: generateRepositorySummary })
  const chat = useMutation({ mutationFn: askRepositoryQuestion })

  function handleGenerateSummary() {
    summary.mutate(undefined, {
      onError: (error) => toast.error('Could not generate summary', { description: errorMessage(error) }),
    })
  }

  function handleAsk(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || chat.isPending) return

    chat.mutate(
      { question: trimmed, mode },
      {
        onSuccess: (data) => {
          setConversation((prev) => [{ question: trimmed, mode, ...data }, ...prev])
          setQuestion('')
        },
        onError: (error) => toast.error('Could not get an answer', { description: errorMessage(error) }),
      },
    )
  }

  return (
    <div className="app-shell">
      <div className="app-glow" />
      <div className="app-content">
        <header className="app-header">
          <div className="logo-mark">C</div>
          <span className="logo-text">CodeMap</span>
        </header>
        <main className="app-main">
          <div className="analysis-page">
            <div className="analysis-header">
              <div>
                <h1 className="card-title">{summary.data?.repository_name ?? 'Repository Insights'}</h1>
                <p className="card-subtitle">AI-generated summary and Q&amp;A, grounded in the actual repository.</p>
              </div>
              <button className="btn btn-outline" onClick={onBack}>
                Back
              </button>
            </div>

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

            <div className="panel">
              <h2 className="panel-title">Repository Summary</h2>

              {!summary.data && !summary.isPending && (
                <button className="btn btn-primary" onClick={handleGenerateSummary}>
                  Generate Summary
                </button>
              )}

              {summary.isPending && <p className="card-subtitle">Analyzing repository and generating summary…</p>}

              {summary.data && (
                <>
                  <p className="summary-text">
                    {mode === 'beginner' ? summary.data.beginner_summary : summary.data.developer_summary}
                  </p>
                  <SourcesList sources={summary.data.sources} />
                </>
              )}
            </div>

            <div className="panel">
              <h2 className="panel-title">Ask CodeMap</h2>
              <form className="import-form" onSubmit={handleAsk}>
                <input
                  className="input"
                  type="text"
                  placeholder="How does authentication work?"
                  value={question}
                  disabled={chat.isPending}
                  onChange={(event) => setQuestion(event.target.value)}
                />
                <button type="submit" className="btn btn-primary" disabled={chat.isPending || !question.trim()}>
                  {chat.isPending ? 'Thinking…' : 'Ask'}
                </button>
              </form>

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
          </div>
        </main>
      </div>
    </div>
  )
}
