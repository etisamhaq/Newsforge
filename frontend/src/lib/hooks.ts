import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

/** id -> name lookup for showing source names next to jobs and articles. */
export function useSourceNames(): Map<number, string> {
  const { data } = useQuery({ queryKey: ['sources'], queryFn: () => api.sources(), staleTime: 60_000 })
  return useMemo(() => new Map((data?.items ?? []).map((s) => [s.id, s.name])), [data])
}
