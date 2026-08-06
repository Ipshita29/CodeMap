import { useMutation } from '@tanstack/react-query'

import { importRepository } from '@/services/repository-service'

export function useImportRepository() {
  return useMutation({
    mutationFn: importRepository,
  })
}
