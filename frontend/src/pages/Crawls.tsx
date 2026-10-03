import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtDateTime, fmtDuration, fmtNumber } from '../lib/format'
import { useSourceNames } from '../lib/hooks'
import type { JobStatus } from '../lib/types'
import { EmptyState, ErrorNotice, PageHeader, Pagination, SourceLink, Spinner, StatusBadge } from '../components/ui'

const LIMIT = 25
const FILTERS: { value: '' | JobStatus; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'running', label: 'Running' },
  { value: 'pending', label: 'Queued' },
  { value: 'succeeded', label: 'Succeeded' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
]

export function Crawls() {
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const sourceId = params.get('source_id') ? Number(params.get('source_id')) : undefined
  const offset = Number(params.get('offset') ?? 0)
  const names = useSourceNames()

  const { data, error, refetch, isPending } = useQuery({
    queryKey: ['crawls', { status, sourceId, offset }],
    queryFn: () => api.crawls({ status: status || undefined, source_id: sourceId, limit: LIMIT, offset }),
    // Poll while anything on screen is still in flight.
    refetchInterval: (q) => (q.state.data?.items.some((j) => j.status === 'running' || j.status === 'pending') ? 4000 : 30_000),
  })

  const update = (next: Record<string, string | undefined>) => {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v) p.set(k, v)
      else p.delete(k)
    }
    setParams(p)
  }

  return (
    <>
      <PageHeader
        title="Crawls"
        intro={sourceId ? <>Crawls of {names.get(sourceId) ?? `source ${sourceId}`}. <Link to="/crawls">Show all sources</Link></> : 'Every crawl run, newest first.'}
      />
      <div className="segmented" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            aria-pressed={status === f.value}
            onClick={() => update({ status: f.value || undefined, offset: undefined })}
          >
            {f.label}
          </button>
        ))}
      </div>
      {isPending && <Spinner />}
      {error && <ErrorNotice error={error} onRetry={refetch} />}
      {data && data.items.length === 0 && (
        <EmptyState title="No crawls here">Start a crawl from a source page, or wait for the next scheduled run.</EmptyState>
      )}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Crawl</th>
                <th scope="col">Source</th>
                <th scope="col">Status</th>
                <th scope="col">Started</th>
                <th scope="col">Duration</th>
                <th scope="col" className="num">
                  Pages
                </th>
                <th scope="col" className="num">
                  New articles
                </th>
                <th scope="col" className="num">
                  Duplicates
                </th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((j) => (
                <tr key={j.id}>
                  <td>
                    <Link to={`/crawls/${j.id}`} className="strong">
                      #{j.id}
                    </Link>
                    <span className="sub">{j.trigger === 'scheduled' ? 'Scheduled' : 'Manual'}</span>
                  </td>
                  <td>
                    <SourceLink id={j.source_id} names={names} />
                  </td>
                  <td>
                    <StatusBadge status={j.status} />
                  </td>
                  <td>{fmtDateTime(j.started_at ?? j.created_at)}</td>
                  <td>{fmtDuration(j.started_at, j.finished_at)}</td>
                  <td className="num">{fmtNumber(j.pages_fetched)}</td>
                  <td className="num">{fmtNumber(j.articles_new)}</td>
                  <td className="num">{fmtNumber(j.duplicates)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={(o) => update({ offset: String(o) })} />}
    </>
  )
}
