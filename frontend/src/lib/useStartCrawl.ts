import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from './api'
import { useToast } from '../components/toast'

/** Start a crawl, then jump to its live progress page. */
export function useStartCrawl() {
  const queryClient = useQueryClient()
  const notify = useToast()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: (sourceId: number) => api.startCrawl(sourceId),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ['crawls'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      notify('Crawl started')
      navigate(`/crawls/${job.id}`)
    },
    onError: (err) => {
      notify(
        err instanceof ApiError && err.status === 409
          ? 'This source is already being crawled.'
          : err instanceof Error
            ? err.message
            : 'Could not start the crawl.',
        'error',
      )
    },
  })
}
