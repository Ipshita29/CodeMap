import { apiRequest } from '@/services/api-client'

export function fetchRepositoryAnalysis() {
  return apiRequest('/repository/analyze', { method: 'GET' })
}
