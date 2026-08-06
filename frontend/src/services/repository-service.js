import { apiRequest } from '@/services/api-client'

export function importRepository(payload) {
  return apiRequest('/repository/import', {
    method: 'POST',
    body: payload,
  })
}
