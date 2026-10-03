import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtNumber, fmtRelative, fmtTime, languageName } from '../lib/format'
import { useSourceNames } from '../lib/hooks'
import type { JobStatus, Stats } from '../lib/types'
import { DailyBars, RankedBars } from '../components/charts'
import { EmptyState, ErrorNotice, Meter, PageHeader, Spinner, StatusBadge } from '../components/ui'

const STAGES: { key: keyof Stats['last_24h']; label: string; hint: string }[] = [
  { key: 'discovered', label: 'Discovered', hint: 'URLs found in feeds, sitemaps and links' },
  { key: 'fetched', label: 'Fetched', hint: 'Pages downloaded' },
  { key: 'articles', label: 'Articles', hint: 'Pages classified as articles' },
  { key: 'new', label: 'New', hint: 'Stories added to the archive' },
  { key: 'duplicates', label: 'Duplicates', hint: 'Copies linked to an existing story' },
]

function Pipeline({ stats }: { stats: Stats }) {
  const p = stats.last_24h
  return (
    <section className="pipeline" aria-labelledby="pipeline-title">
      <h2 id="pipeline-title" className="section-title">
        Last 24 hours
      </h2>
      <ol className="pipeline-stages">
        {STAGES.map((s) => (
          <li key={s.key} className={`stage stage-${s.key}`}>
            <span className="stage-value">{fmtNumber(p[s.key])}</span>
            <span className="stage-label">{s.label}</span>
            <span className="stage-hint">{s.hint}</span>
          </li>
        ))}
      </ol>
      {(p.failed > 0 || p.robots_blocked > 0) && (
        <p className="pipeline-note">
          {p.failed > 0 && <span>{fmtNumber(p.failed)} pages failed to load. </span>}
          {p.robots_blocked > 0 && <span>{fmtNumber(p.robots_blocked)} pages skipped because robots.txt disallows them.</span>}
        </p>
      )}
    </section>
  )
}

function Wire() {
  const names = useSourceNames()
  const { data, error, refetch, isPending } = useQuery({
    queryKey: ['articles', 'wire'],
    queryFn: () => api.articles({ sort: 'created', limit: 12 }),
    refetchInterval: 30_000,
  })
  return (
    <section className="wire" aria-labelledby="wire-title">
      <div className="section-head">
        <h2 id="wire-title" className="section-title">
          Latest stories
        </h2>
        <Link to="/articles?sort=created">All articles</Link>
      </div>
      {isPending && <Spinner />}
      {error && <ErrorNotice error={error} onRetry={refetch} />}
      {data && data.items.length === 0 && (
        <EmptyState title="No articles yet">Add a source and start a crawl to fill the archive.</EmptyState>
      )}
      <ol className="wire-list">
        {data?.items.map((a) => (
          <li key={a.id} className="wire-item">
            <time dateTime={a.created_at} className="wire-time" title={new Date(a.created_at).toLocaleString()}>
              {fmtTime(a.created_at)}
            </time>
            <div className="wire-body">
              <Link to={`/articles/${a.id}`} className="headline">
                {a.title ?? a.url}
              </Link>
              <p className="wire-meta">
                <span>{a.source_id != null ? names.get(a.source_id) : a.site_name}</span>
                <span>{languageName(a.language)}</span>
                {a.published_at && <span>Published {fmtRelative(a.published_at)}</span>}
              </p>
            </div>
            <Meter value={a.confidence} label="Extraction confidence" />
          </li>
        ))}
      </ol>
    </section>
  )
}

function SourcesHealth({ stats }: { stats: Stats }) {
  if (stats.sources.length === 0) return null
  return (
    <section aria-labelledby="sources-health-title">
      <div className="section-head">
        <h2 id="sources-health-title" className="section-title">
          Sources
        </h2>
        <Link to="/sources">Manage</Link>
      </div>
      <table className="table table-compact">
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col" className="num">
              Articles
            </th>
            <th scope="col">Last crawl</th>
          </tr>
        </thead>
        <tbody>
          {stats.sources.map((s) => (
            <tr key={s.id}>
              <td>
                <Link to={`/sources/${s.id}`}>{s.name}</Link>
                {!s.enabled && <span className="tag">Paused</span>}
              </td>
              <td className="num">{fmtNumber(s.articles)}</td>
              <td>
                {s.last_status ? <StatusBadge status={s.last_status} /> : <span className="muted">Never crawled</span>}
                <span className="muted small"> {s.last_crawl_at ? fmtRelative(s.last_crawl_at) : ''}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export function Dashboard() {
  const { can } = useAuth()
  const { data: stats, error, refetch, isPending } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.stats(14),
    refetchInterval: 30_000,
  })

  const active = (stats?.jobs_by_status.running ?? 0) + (stats?.jobs_by_status.pending ?? 0)
  return (
    <>
      <PageHeader
        title="Dashboard"
        intro={
          stats
            ? `${fmtNumber(stats.totals.articles)} ${stats.totals.articles === 1 ? 'story' : 'stories'} from ${fmtNumber(stats.totals.sources)} ${stats.totals.sources === 1 ? 'source' : 'sources'}. ${
                active > 0 ? `${active} crawl${active === 1 ? '' : 's'} in progress.` : 'No crawls running.'
              }`
            : undefined
        }
        actions={
          can('editor') && (
            <Link to="/sources?new=1" className="btn btn-primary">
              Add source
            </Link>
          )
        }
      />
      {isPending && <Spinner />}
      {error && <ErrorNotice error={error} onRetry={refetch} />}
      {stats && (
        <>
          <Pipeline stats={stats} />
          <div className="dash-grid">
            <Wire />
            <div className="dash-side">
              <section aria-labelledby="volume-title">
                <h2 id="volume-title" className="section-title">
                  New articles per day
                </h2>
                <DailyBars data={stats.articles_per_day} />
              </section>
              {stats.languages.length > 0 && (
                <section aria-labelledby="lang-title">
                  <h2 id="lang-title" className="section-title">
                    Languages
                  </h2>
                  <RankedBars data={stats.languages} />
                </section>
              )}
              <section aria-labelledby="jobs-title">
                <div className="section-head">
                  <h2 id="jobs-title" className="section-title">
                    Crawl outcomes
                  </h2>
                  <Link to="/crawls">All crawls</Link>
                </div>
                <ul className="status-counts">
                  {(['running', 'pending', 'succeeded', 'failed', 'cancelled'] as JobStatus[]).map((s) => (
                    <li key={s}>
                      <StatusBadge status={s} />
                      <span className="num">{fmtNumber(stats.jobs_by_status[s] ?? 0)}</span>
                    </li>
                  ))}
                </ul>
              </section>
              <SourcesHealth stats={stats} />
            </div>
          </div>
        </>
      )}
    </>
  )
}
