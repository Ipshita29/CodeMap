import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError, importRepository, isValidGitHubUrl } from '@/api'

export function LandingPage({ onViewAnalysis }) {
  const [githubUrl, setGithubUrl] = useState('')
  const [validationError, setValidationError] = useState(null)
  const { mutate, data, isPending, isSuccess, reset } = useMutation({ mutationFn: importRepository })

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
        onError: (error) => {
          const message = error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
          toast.error('Import failed', { description: message })
        },
      },
    )
  }

  function handleImportAnother() {
    setGithubUrl('')
    setValidationError(null)
    reset()
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
          {isSuccess && data ? (
            <div className="card card-center">
              <div className="success-icon-wrap">
                <CheckCircle2 className="success-icon" size={24} />
              </div>
              <h2 className="card-title">Repository imported</h2>
              <p className="repo-name">{data.repository_name}</p>
              <p className="clone-path">{data.clone_path}</p>
              <button className="btn btn-primary btn-block mt-6" onClick={onViewAnalysis}>
                View Analysis
              </button>
              <button className="btn btn-outline btn-block mt-3" onClick={handleImportAnother}>
                Import another repository
              </button>
            </div>
          ) : (
            <div className="card">
              <h1 className="card-title">Understand any repository</h1>
              <p className="card-subtitle">Paste a public GitHub repository URL to get started.</p>

              <form className="import-form" onSubmit={handleSubmit} noValidate>
                <div className="field">
                  <input
                    className="input"
                    type="text"
                    inputMode="url"
                    placeholder="https://github.com/owner/repo"
                    value={githubUrl}
                    disabled={isPending}
                    onChange={(event) => {
                      setGithubUrl(event.target.value)
                      if (validationError) setValidationError(null)
                    }}
                    aria-invalid={validationError ? 'true' : 'false'}
                  />
                  {validationError && <p className="field-error">{validationError}</p>}
                </div>

                <button type="submit" className="btn btn-primary btn-block" disabled={isPending}>
                  {isPending ? (
                    <>
                      <Loader2 className="spinner" size={16} />
                      Importing repository…
                    </>
                  ) : (
                    'Import repository'
                  )}
                </button>
              </form>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
