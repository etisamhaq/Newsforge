import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtDateTime, fmtDuration, fmtNumber, stopReasonLabel } from '../lib/format'
import { useSourceNames } from '../lib/hooks'
import { useToast } from '../components/toast'
import { ErrorNotice, PageHeader, SourceLink, Spinner, StatusBadge } from '../components/ui'

export function CrawlDetail() {
  const id = Number(useParams().id)
  const names = useSourceNames()
  const queryClient = useQueryClient()
  const notify = useToast()
  const { data: job, error, refetch, isPending } = useQuery({
    queryKey: ['crawl', id],
    queryFn: () => api.crawl(id),
    refetchInterval: (q) => (q.state.data && ['pending', 'running'].includes(q.state.data.status) ? 2500 : false),
  })
  const cancel = useMutation({
    mutationFn: () => api.cancelCrawl(id),
    onSuccess: (j) => {
      queryClient.setQueryData(['crawl', id], j)
      queryClient.invalidateQueries({ queryKey: ['crawls'] })
      notify('Cancel requested. The crawl stops after its current pages.')
    },
    onError: (e) => notify(e instanceof Error ? e.message : 'Could not cancel the crawl.', 'error'),
  })

  if (isPending) return <Spinner />
  if (error) return <ErrorNotice error={error} onRetry={refetch} />

  const st = job.stats ?? {}
  const active = job.status === 'pending' || job.status === 'running'
  const counters: [string, number | undefined][] = [
    ['Pages fetched', job.pages_fetched],
    ['Feeds and sitemaps read', st.seed_fetches],
    ['URLs discovered', st.discovered],
    ['Articles found', job.articles_found],
    ['New articles', job.articles_new],
    ['Updated articles', job.articles_updated],
    ['Duplicates', job.duplicates],
    ['Unchanged (HTTP 304)', st.not_modified],
    ['Skipped', job.pages_skipped],
    ['Blocked by robots.txt', st.robots_blocked],
    ['Rendered in a browser', st.rendered],
    ['Failed', job.pages_failed],
  ]

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/crawls">Crawls</Link>
      </nav>
      <PageHeader
        title={`Crawl #${job.id}`}
        intro={
          <>
            {job.trigger === "scheduled" ? "Scheduled crawl of " : "Manual crawl of "}<SourceLink id={job.source_id} names={names} />
          </>
        }
        actions={
          active && (
            <button type="button" className="btn btn-quiet" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              Cancel crawl
            </button>
          )
        }
      />
      <div className="crawl-summary">
        <StatusBadge status={job.status} />
        <dl className="inline-facts">
          <div>
            <dt>Started</dt>
            <dd>{fmtDateTime(job.started_at)}</dd>
          </div>
          <div>
            <dt>{active ? 'Running for' : 'Took'}</dt>
            <dd>{fmtDuration(job.started_at, job.finished_at)}</dd>
          </div>
          {!active && (
            <div>
              <dt>Stopped because</dt>
              <dd>{stopReasonLabel(st.stopped_reason)}</dd>
            </div>
          )}
        </dl>
      </div>
      {job.error && (
        <div className="notice notice-error" role="alert">
          <p>{job.error}</p>
        </div>
      )}
      {st.hosts_unreachable && st.hosts_unreachable.length > 0 && (
        <div className="notice notice-warning">
          <p>
            Stopped requesting {st.hosts_unreachable.join(', ')} after repeated network failures. The site may be down or
            blocking the crawler.
          </p>
        </div>
      )}
      <section aria-labelledby="counters-title">
        <h2 id="counters-title" className="section-title">
          Results
        </h2>
        <dl className="counters">
          {counters.map(([label, value]) => (
            <div key={label} className={label === 'Failed' && (value ?? 0) > 0 ? 'is-bad' : !value ? 'is-zero' : undefined}>
              <dd>{fmtNumber(value ?? 0)}</dd>
              <dt>{label}</dt>
            </div>
          ))}
        </dl>
      </section>
      {st.errors && st.errors.length > 0 && (
        <section aria-labelledby="errors-title">
          <h2 id="errors-title" className="section-title">
            Errors
          </h2>
          <p className="muted">The most recent {st.errors.length} problems from this crawl.</p>
          <ul className="error-list">
            {st.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </section>
      )}
      {job.articles_new > 0 && !active && (
        <p>
          <Link to={`/articles?source_id=${job.source_id}&sort=created`}>See the articles from this source</Link>
        </p>
      )}
    </>
  )
}
