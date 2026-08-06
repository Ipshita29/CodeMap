import { useQuery } from '@tanstack/react-query'

import { fetchRepositoryAnalysis } from '@/services/analysis-service'

export function useRepositoryAnalysis() {
  return useQuery({
    queryKey: ['repository-analysis'],
    queryFn: fetchRepositoryAnalysis,
  })
}
