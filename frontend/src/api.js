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

  return response.json()
}

export function importRepository(payload) {
  return apiRequest('/repository/import', { method: 'POST', body: payload })
}

export function fetchRepositoryAnalysis() {
  return apiRequest('/repository/analyze', { method: 'GET' })
}

export function generateRepositorySummary() {
  return apiRequest('/repository/summary', { method: 'POST' })
}

export function askRepositoryQuestion({ question, mode }) {
  return apiRequest('/repository/chat', { method: 'POST', body: { question, mode } })
}

export function fetchCodeIntelligence() {
  return apiRequest('/repository/code-intelligence', { method: 'GET' })
}

export function fetchRepositoryGraph({ focus } = {}) {
  const query = focus ? `?focus=${encodeURIComponent(focus)}` : ''
  return apiRequest(`/repository/graph${query}`, { method: 'GET' })
}

export function analyzeChangeImpact(payload) {
  return apiRequest('/repository/impact', { method: 'POST', body: payload })
}

export function fetchGitSummary() {
  return apiRequest('/repository/git/summary', { method: 'GET' })
}

export function fetchGitHistory({ limit } = {}) {
  const query = limit ? `?limit=${encodeURIComponent(limit)}` : ''
  return apiRequest(`/repository/git/history${query}`, { method: 'GET' })
}

export function fetchFileGitHistory(path) {
  return apiRequest(`/repository/git/file-history?path=${encodeURIComponent(path)}`, { method: 'GET' })
}

export function fetchRepositoryHealth() {
  return apiRequest('/repository/health', { method: 'GET' })
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
