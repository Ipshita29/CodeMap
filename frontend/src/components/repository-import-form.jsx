import { useState } from 'react'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useImportRepository } from '@/hooks/use-import-repository'
import { isValidGitHubUrl } from '@/lib/validate-github-url'
import { ApiError } from '@/services/api-client'

export function RepositoryImportForm({ onViewAnalysis }) {
  const [githubUrl, setGithubUrl] = useState('')
  const [validationError, setValidationError] = useState(null)
  const { mutate, data, isPending, isSuccess, reset } = useImportRepository()

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

  if (isSuccess && data) {
    return (
      <Card className="card-center">
        <div className="success-icon-wrap">
          <CheckCircle2 className="success-icon" size={24} />
        </div>
        <h2 className="card-title">Repository imported</h2>
        <p className="repo-name">{data.repository_name}</p>
        <p className="clone-path">{data.clone_path}</p>
        <Button block className="mt-6" onClick={onViewAnalysis}>
          View Analysis
        </Button>
        <Button variant="outline" block className="mt-3" onClick={handleImportAnother}>
          Import another repository
        </Button>
      </Card>
    )
  }

  return (
    <Card>
      <h1 className="card-title">Understand any repository</h1>
      <p className="card-subtitle">Paste a public GitHub repository URL to get started.</p>

      <form className="import-form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <Input
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

        <Button type="submit" block disabled={isPending}>
          {isPending ? (
            <>
              <Loader2 className="spinner" size={16} />
              Importing repository…
            </>
          ) : (
            'Import repository'
          )}
        </Button>
      </form>
    </Card>
  )
}
