import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtNumber, fmtRelative, intervalLabel } from '../lib/format'
import { useStartCrawl } from '../lib/useStartCrawl'
import { SourceForm } from '../components/SourceForm'
import { IconPlay } from '../components/icons'
import { Dialog, EmptyState, ErrorNotice, PageHeader, Spinner, StatusBadge } from '../components/ui'

export function Sources() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const { can } = useAuth()
  const canEdit = can('editor')
  const creating = canEdit && params.get('new') === '1'
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api.sources() })
  const stats = useQuery({ queryKey: ['stats'], queryFn: () => api.stats(14) })
  const startCrawl = useStartCrawl()
  const bySource = new Map((stats.data?.sources ?? []).map((s) => [s.id, s]))

  const openNew = () => setParams({ new: '1' })
  const close = () => setParams({})

  return (
    <>
      <PageHeader
        title="Sources"
        intro="News sites Newsforge crawls. Each one runs on its own schedule and limits."
        actions={
          canEdit && (
            <button type="button" className="btn btn-primary" onClick={openNew}>
              Add source
            </button>
          )
        }
      />
      {sources.isPending && <Spinner />}
      {sources.error && <ErrorNotice error={sources.error} onRetry={sources.refetch} />}
      {sources.data && sources.data.items.length === 0 && (
        <EmptyState
          title="No sources yet"
          action={
            canEdit && (
              <button type="button" className="btn btn-primary" onClick={openNew}>
                Add your first source
              </button>
            )
          }
        >
          {canEdit ? 'Add a news site by its homepage. Feeds and sitemaps are found automatically.' : 'An editor or admin can add news sites to crawl.'}
        </EmptyState>
      )}
      {sources.data && sources.data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Schedule</th>
                <th scope="col" className="num">
                  Articles
                </th>
                <th scope="col">Last crawl</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sources.data.items.map((s) => {
                const health = bySource.get(s.id)
                return (
                  <tr key={s.id}>
                    <td>
                      <Link to={`/sources/${s.id}`} className="strong">
                        {s.name}
                      </Link>
                      <span className="sub">{s.domain}</span>
                    </td>
                    <td>
                      {s.enabled ? intervalLabel(s.crawl_interval_minutes) : <span className="tag">Paused</span>}
                      {s.enabled && s.next_crawl_at && <span className="sub">Next {fmtRelative(s.next_crawl_at)}</span>}
                    </td>
                    <td className="num">{fmtNumber(health?.articles ?? 0)}</td>
                    <td>
                      {health?.last_status ? <StatusBadge status={health.last_status} /> : <span className="muted">Never</span>}
                      {s.last_crawl_at && <span className="sub">{fmtRelative(s.last_crawl_at)}</span>}
                    </td>
                    <td className="actions">
                      {canEdit && (
                      <button
                        type="button"
                        className="btn btn-quiet btn-small"
                        onClick={() => startCrawl.mutate(s.id)}
                        disabled={startCrawl.isPending}
                      >
                        <IconPlay size={14} />
                        Crawl now
                      </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <Dialog open={creating} onClose={close} title="Add a source" wide>
        <SourceForm onDone={(s) => navigate(`/sources/${s.id}`)} />
      </Dialog>
    </>
  )
}
