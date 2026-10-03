import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtDateTime, fmtDuration, fmtNumber, fmtRelative, intervalLabel, languageName } from '../lib/format'
import { useStartCrawl } from '../lib/useStartCrawl'
import { SourceForm } from '../components/SourceForm'
import { IconPlay } from '../components/icons'
import { useToast } from '../components/toast'
import { Dialog, EmptyState, ErrorNotice, ExternalLink, Meter, PageHeader, Spinner, StatusBadge } from '../components/ui'

const RENDER_LABEL = { auto: 'When needed', always: 'Always', never: 'Never' }

export function SourceDetail() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const notify = useToast()
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const startCrawl = useStartCrawl()

  const source = useQuery({ queryKey: ['source', id], queryFn: () => api.source(id) })
  const jobs = useQuery({
    queryKey: ['crawls', { source_id: id }],
    queryFn: () => api.crawls({ source_id: id, limit: 10 }),
    refetchInterval: (q) => (q.state.data?.items.some((j) => j.status === 'running' || j.status === 'pending') ? 4000 : false),
  })
  const articles = useQuery({
    queryKey: ['articles', { source_id: id, wire: true }],
    queryFn: () => api.articles({ source_id: id, sort: 'created', limit: 8 }),
  })

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.updateSource(id, { enabled }),
    onSuccess: (s) => {
      queryClient.setQueryData(['source', id], s)
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      notify(s.enabled ? 'Scheduled crawling resumed' : 'Scheduled crawling paused')
    },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteSource(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      notify('Source deleted')
      navigate('/sources')
    },
    onError: (e) => notify(e instanceof Error ? e.message : 'Could not delete the source.', 'error'),
  })

  if (source.isPending) return <Spinner />
  if (source.error) return <ErrorNotice error={source.error} onRetry={source.refetch} />
  const s = source.data

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/sources">Sources</Link>
      </nav>
      <PageHeader
        title={s.name}
        intro={<ExternalLink href={s.base_url}>{s.base_url}</ExternalLink>}
        actions={
          <>
            <button type="button" className="btn btn-quiet" onClick={() => setEditing(true)}>
              Edit
            </button>
            <button type="button" className="btn btn-primary" onClick={() => startCrawl.mutate(id)} disabled={startCrawl.isPending}>
              <IconPlay size={16} />
              Crawl now
            </button>
          </>
        }
      />

      <div className="detail-grid">
        <section aria-labelledby="config-title">
          <h2 id="config-title" className="section-title">
            Configuration
          </h2>
          <dl className="facts">
            <dt>Schedule</dt>
            <dd>
              {s.enabled ? intervalLabel(s.crawl_interval_minutes) : 'Paused'}
              {s.enabled && s.next_crawl_at && <span className="sub">Next crawl {fmtRelative(s.next_crawl_at)}</span>}
            </dd>
            <dt>Limits</dt>
            <dd>
              {fmtNumber(s.max_pages)} pages, {s.max_depth === 0 ? 'no link following' : `${s.max_depth} ${s.max_depth === 1 ? 'link' : 'links'} deep`},{' '}
              {s.min_delay_seconds}s between requests
            </dd>
            <dt>Domains</dt>
            <dd>{s.allowed_domains.join(', ')}</dd>
            <dt>Feeds</dt>
            <dd>{s.feed_urls.length ? s.feed_urls.map((f) => <span key={f} className="url-line">{f}</span>) : 'Discovered automatically'}</dd>
            {s.sitemap_urls.length > 0 && (
              <>
                <dt>Sitemaps</dt>
                <dd>
                  {s.sitemap_urls.map((f) => (
                    <span key={f} className="url-line">
                      {f}
                    </span>
                  ))}
                </dd>
              </>
            )}
            <dt>JavaScript rendering</dt>
            <dd>{RENDER_LABEL[s.render_mode]}</dd>
            <dt>Follow links</dt>
            <dd>{s.discover_links ? 'Yes' : 'No'}</dd>
            <dt>Raw HTML</dt>
            <dd>{s.store_raw_html ? 'Kept' : 'Not kept'}</dd>
          </dl>
          <div className="button-row">
            <button type="button" className="btn btn-quiet btn-small" onClick={() => toggle.mutate(!s.enabled)} disabled={toggle.isPending}>
              {s.enabled ? 'Pause scheduled crawling' : 'Resume scheduled crawling'}
            </button>
            <button type="button" className="btn btn-danger-quiet btn-small" onClick={() => setConfirmDelete(true)}>
              Delete source
            </button>
          </div>
        </section>

        <section aria-labelledby="jobs-title">
          <div className="section-head">
            <h2 id="jobs-title" className="section-title">
              Recent crawls
            </h2>
            <Link to={`/crawls?source_id=${id}`}>All crawls</Link>
          </div>
          {jobs.data?.items.length === 0 && <p className="muted">This source hasn't been crawled yet.</p>}
          <ul className="job-list">
            {jobs.data?.items.map((j) => (
              <li key={j.id}>
                <Link to={`/crawls/${j.id}`} className="job-row">
                  <StatusBadge status={j.status} />
                  <span>{fmtDateTime(j.created_at)}</span>
                  <span className="muted">{fmtDuration(j.started_at, j.finished_at)}</span>
                  <span className="num">{fmtNumber(j.articles_new)} new</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section aria-labelledby="src-articles-title">
        <div className="section-head">
          <h2 id="src-articles-title" className="section-title">
            Latest articles
          </h2>
          <Link to={`/articles?source_id=${id}`}>All articles from {s.name}</Link>
        </div>
        {articles.data?.items.length === 0 && <EmptyState title="No articles yet">Run a crawl to collect stories from this source.</EmptyState>}
        <ul className="article-list">
          {articles.data?.items.map((a) => (
            <li key={a.id}>
              <Link to={`/articles/${a.id}`} className="headline">
                {a.title ?? a.url}
              </Link>
              <span className="article-list-meta">
                <span>{languageName(a.language)}</span>
                <span>{fmtRelative(a.published_at ?? a.created_at)}</span>
                <Meter value={a.confidence} label="Extraction confidence" />
              </span>
            </li>
          ))}
        </ul>
      </section>

      <Dialog open={editing} onClose={() => setEditing(false)} title={`Edit ${s.name}`} wide>
        <SourceForm source={s} onDone={() => setEditing(false)} />
      </Dialog>
      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title={`Delete ${s.name}?`}>
        <p>
          This removes the source and its crawl history. Articles already collected stay in the archive but lose their link to this
          source.
        </p>
        <div className="form-actions">
          <button type="button" className="btn btn-quiet" onClick={() => setConfirmDelete(false)}>
            Keep source
          </button>
          <button type="button" className="btn btn-danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
            {remove.isPending ? 'Deleting…' : 'Delete source'}
          </button>
        </div>
      </Dialog>
    </>
  )
}
