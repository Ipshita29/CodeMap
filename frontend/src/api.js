const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const GITHUB_URL_PATTERN =
  /^https:\/\/github\.com\/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?(?:\.git)?\/?$/

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function isValidGitHubUrl(url) {
  return GITHUB_URL_PATTERN.test(url.trim())
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })

  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const message =
      (payload && typeof payload === 'object' && 'detail' in payload
        ? String(payload.detail)
        : undefined) ?? `Request failed with status ${response.status}`
    throw new ApiError(message, response.status)
  }

  if (response.status === 204) return null
  return response.json()
}

// Every function below except importRepository takes an explicit
// `repositoryId` as its first argument -- the `repository_name` returned by
// importRepository -- and sends it to the backend on every request. The
// backend resolves "which repository" strictly from this value; there is no
// server-side notion of "the current repository" to fall back on, so a
// stale or missing id fails loudly (404) rather than silently resolving to
// someone else's imported repository.

export function importRepository(payload) {
  return apiRequest('/repository/import', { method: 'POST', body: payload })
}

export function fetchRepositoryAnalysis(repositoryId) {
  return apiRequest(`/repository/analyze?repository_id=${encodeURIComponent(repositoryId)}`, { method: 'GET' })
}

export function generateRepositorySummary(repositoryId) {
  return apiRequest(`/repository/summary?repository_id=${encodeURIComponent(repositoryId)}`, { method: 'POST' })
}

export function askRepositoryQuestion(repositoryId, { question, mode }) {
  return apiRequest('/repository/chat', {
    method: 'POST',
    body: { repository_id: repositoryId, question, mode },
  })
}

export function fetchChatHistory(repositoryId) {
  return apiRequest(`/repository/chat/history?repository_id=${encodeURIComponent(repositoryId)}`, { method: 'GET' })
}

export function clearChatHistory(repositoryId) {
  return apiRequest(`/repository/chat/history?repository_id=${encodeURIComponent(repositoryId)}`, {
    method: 'DELETE',
  })
}

export function fetchCodeIntelligence(repositoryId) {
  return apiRequest(`/repository/code-intelligence?repository_id=${encodeURIComponent(repositoryId)}`, {
    method: 'GET',
  })
}

export function fetchRepositoryTree(repositoryId) {
  return apiRequest(`/repository/tree?repository_id=${encodeURIComponent(repositoryId)}`, { method: 'GET' })
}

export function fetchRepositoryGraph(repositoryId, { focus } = {}) {
  const query = focus ? `&focus=${encodeURIComponent(focus)}` : ''
  return apiRequest(`/repository/graph?repository_id=${encodeURIComponent(repositoryId)}${query}`, {
    method: 'GET',
  })
}

export function analyzeChangeImpact(repositoryId, payload) {
  return apiRequest('/repository/impact', { method: 'POST', body: { repository_id: repositoryId, ...payload } })
}

export function fetchGitSummary(repositoryId) {
  return apiRequest(`/repository/git/summary?repository_id=${encodeURIComponent(repositoryId)}`, { method: 'GET' })
}

export function fetchGitHistory(repositoryId, { limit } = {}) {
  const query = limit ? `&limit=${encodeURIComponent(limit)}` : ''
  return apiRequest(`/repository/git/history?repository_id=${encodeURIComponent(repositoryId)}${query}`, {
    method: 'GET',
  })
}

export function fetchFileGitHistory(repositoryId, path) {
  return apiRequest(
    `/repository/git/file-history?repository_id=${encodeURIComponent(repositoryId)}&path=${encodeURIComponent(path)}`,
    { method: 'GET' },
  )
}

export function fetchRepositoryHealth(repositoryId) {
  return apiRequest(`/repository/health?repository_id=${encodeURIComponent(repositoryId)}`, { method: 'GET' })
}

export async function exportPdf({ title, markdown }) {
  const response = await fetch(`${API_BASE_URL}/repository/export/pdf`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, markdown }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(payload?.detail ?? `Request failed with status ${response.status}`, response.status)
  }
  return response.blob()
}
