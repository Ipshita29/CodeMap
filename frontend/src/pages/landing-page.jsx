import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError, importRepository, isValidGitHubUrl } from '@/api'

const CAPABILITIES = [
  { title: 'Architecture', body: 'Understand how the codebase is structured.' },
  { title: 'Git Intelligence', body: 'Understand what changed and where.' },
  { title: 'Code Health', body: 'Find complexity and structural hotspots.' },
]

const AI_EXAMPLES = [
  'How does authentication work?',
  'Where is payment logic handled?',
  'What are the most important files?',
  'How does package X depend on package Y?',
]

// A small static diagram in the existing graph-node visual language, not a
// real product screenshot -- avoids fabricating one while still giving the
// landing page something concrete to show under "product preview."
function GraphPreview() {
  return (
    <svg viewBox="0 0 560 200" width="100%" role="img" aria-label="Preview of a repository dependency graph">
      <g stroke="var(--card-border)" strokeWidth="1.5" fill="none">
        <path d="M120 60 L260 100" />
        <path d="M120 140 L260 100" />
        <path d="M260 100 L400 60" />
        <path d="M260 100 L400 100" />
        <path d="M260 100 L400 140" />
      </g>
      {[
        { x: 40, y: 42, w: 80, h: 36, label: 'auth.ts', variant: 'accent' },
        { x: 40, y: 122, w: 80, h: 36, label: 'routes.ts', variant: 'accent' },
        { x: 220, y: 82, w: 80, h: 36, label: 'core', variant: 'accent' },
        { x: 400, y: 42, w: 100, h: 36, label: 'db.ts', variant: 'muted' },
        { x: 400, y: 82, w: 100, h: 36, label: 'client.tsx', variant: 'muted' },
        { x: 400, y: 122, w: 100, h: 36, label: 'jwt', variant: 'success' },
      ].map((node) => (
        <g key={node.label}>
          <rect
            x={node.x}
            y={node.y}
            width={node.w}
            height={node.h}
            rx="6"
            fill="var(--card)"
            stroke={node.variant === 'accent' ? 'var(--accent)' : node.variant === 'success' ? 'var(--success)' : 'var(--card-border)'}
            strokeWidth="1.25"
          />
          <text
            x={node.x + node.w / 2}
            y={node.y + node.h / 2 + 4}
            textAnchor="middle"
            fontSize="11"
            fontFamily="var(--font-mono)"
            fill="var(--foreground)"
          >
            {node.label}
          </text>
        </g>
      ))}
    </svg>
  )
}

export function LandingPage({ onImported }) {
  const [githubUrl, setGithubUrl] = useState('')
  const [validationError, setValidationError] = useState(null)
  const { mutate, isPending } = useMutation({ mutationFn: importRepository })

  function handleSubmit(event) {
    event.preventDefault()

    if (!isValidGitHubUrl(githubUrl)) {
      setValidationError('Enter a valid GitHub repository URL, e.g. https://github.com/owner/repo')
      return
    }

    setValidationError(null)
    mutate(
      { github_url: githubUrl.trim() },
      {
        onSuccess: (data) => onImported(data.repository_name),
        onError: (error) => {
          const message = error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
          toast.error('Import failed', { description: message })
        },
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
          <div className="landing">
            <div className="landing-hero">
              <h1 className="landing-heading">
                Understand any codebase.
                <br />
                <em>Instantly.</em>
              </h1>
              <p className="landing-subheading">
                Turn any repository into a visual map of architecture, dependencies, history and health.
              </p>
            </div>

            <form className="landing-import" onSubmit={handleSubmit} noValidate>
              <div className="landing-import-box">
                <input
                  className="landing-import-input"
                  type="text"
                  inputMode="url"
                  placeholder="github.com/owner/repository"
                  value={githubUrl}
                  disabled={isPending}
                  onChange={(event) => {
                    setGithubUrl(event.target.value)
                    if (validationError) setValidationError(null)
                  }}
                  aria-invalid={validationError ? 'true' : 'false'}
                />
                <button type="submit" className="btn btn-primary" disabled={isPending}>
                  {isPending && <Loader2 className="spinner" size={16} />}
                  {isPending ? 'Analyzing…' : 'Analyze'}
                </button>
              </div>
              {validationError && <p className="field-error">{validationError}</p>}
              <p className="landing-meta">No setup · Public repositories · AI-powered</p>
            </form>

            <div className="landing-section">
              <p className="landing-section-label">Product preview</p>
              <div className="landing-preview">
                <GraphPreview />
              </div>
            </div>

            <div className="landing-section">
              <p className="landing-section-label">Three core capabilities</p>
              <div className="capability-grid">
                {CAPABILITIES.map((capability) => (
                  <div key={capability.title} className="capability-item">
                    <h3>{capability.title}</h3>
                    <p>{capability.body}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="landing-section">
              <p className="landing-section-label">Ask your repository anything</p>
              <div className="landing-ai-examples">
                {AI_EXAMPLES.map((example) => (
                  <div key={example} className="landing-ai-example">
                    &ldquo;{example}&rdquo;
                  </div>
                ))}
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
