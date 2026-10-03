import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime, fmtNumber, languageName } from '../lib/format'
import { useSourceNames } from '../lib/hooks'
import { useToast } from '../components/toast'
import { ErrorNotice, ExternalLink, Meter, SourceLink, Spinner } from '../components/ui'

const FIELD_LABELS: Record<string, string> = {
  title: 'Headline',
  body: 'Body',
  authors: 'Authors',
  published_at: 'Published',
  modified_at: 'Updated',
  description: 'Summary',
  image_url: 'Image',
  category: 'Section',
  tags: 'Tags',
  language: 'Language',
  canonical_url: 'Canonical URL',
  site_name: 'Publication',
}
const METHOD_LABELS: Record<string, string> = {
  jsonld: 'Structured data',
  metatags: 'Page metadata',
  trafilatura: 'Main-text extractor',
  density: 'Text density',
  llm: 'LLM',
}

export function ArticleDetail() {
  const id = Number(useParams().id)
  const names = useSourceNames()
  const notify = useToast()
  const { can } = useAuth()
  const { data: a, error, refetch, isPending } = useQuery({ queryKey: ['article', id], queryFn: () => api.article(id) })
  const dupes = useQuery({ queryKey: ['article', id, 'duplicates'], queryFn: () => api.duplicates(id) })

  const raw = useMutation({
    mutationFn: () => api.rawHtml(id),
    onSuccess: (html) => {
      // Shown as plain text in a new tab: stored third-party HTML never runs in our origin.
      const url = URL.createObjectURL(new Blob([html], { type: 'text/plain;charset=utf-8' }))
      window.open(url, '_blank', 'noopener')
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    },
    onError: (e) => notify(e instanceof Error ? e.message : 'No raw HTML stored.', 'error'),
  })

  if (isPending) return <Spinner />
  if (error) return <ErrorNotice error={error} onRetry={refetch} />

  const sources = a.extra.field_sources ?? {}
  const paragraphs = (a.body ?? '').split(/\n+/).map((p) => p.trim()).filter(Boolean)

  return (
    <article className="reader">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/articles">Articles</Link>
      </nav>
      <div className="reader-grid">
        <div className="reader-main">
          {a.category && <p className="kicker">{a.category}</p>}
          <h1 className="reader-title">{a.title ?? 'Untitled'}</h1>
          {a.description && <p className="reader-dek">{a.description}</p>}
          <p className="byline">
            {a.authors.length > 0 && <span>By {a.authors.join(', ')}</span>}
            {a.published_at && <time dateTime={a.published_at}>{fmtDateTime(a.published_at)}</time>}
          </p>
          {a.duplicate_of_id && (
            <p className="notice notice-info">
              This is a copy of <Link to={`/articles/${a.duplicate_of_id}`}>an earlier story</Link>
              {a.extra.simhash_distance != null ? ' with minor differences.' : '.'}
            </p>
          )}
          {a.image_url && <img className="reader-image" src={a.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" />}
          <div className="reader-body" lang={a.language ?? undefined}>
            {paragraphs.length ? paragraphs.map((p, i) => <p key={i}>{p}</p>) : <p className="muted">No body text was extracted.</p>}
          </div>
        </div>

        <aside className="reader-side" aria-label="Extraction details">
          <section>
            <h2 className="section-title">Source</h2>
            <dl className="facts facts-stacked">
              <dt>Crawled from</dt>
              <dd>
                <SourceLink id={a.source_id} names={names} />
              </dd>
              <dt>Original page</dt>
              <dd>
                <ExternalLink href={a.canonical_url}>{a.site_name ?? 'Open original'}</ExternalLink>
              </dd>
              <dt>Language</dt>
              <dd>{languageName(a.language)}</dd>
              <dt>Length</dt>
              <dd>{fmtNumber(a.word_count)} words</dd>
              <dt>Collected</dt>
              <dd>{fmtDateTime(a.created_at)}</dd>
              {a.tags.length > 0 && (
                <>
                  <dt>Tags</dt>
                  <dd className="tags">
                    {a.tags.map((t) => (
                      <span key={t} className="tag">
                        {t}
                      </span>
                    ))}
                  </dd>
                </>
              )}
            </dl>
          </section>
          <section>
            <h2 className="section-title">Extraction quality</h2>
            <dl className="facts facts-stacked">
              <dt>Confidence</dt>
              <dd>
                <Meter value={a.confidence} label="Extraction confidence" />
              </dd>
              <dt>Article likelihood</dt>
              <dd>
                <Meter value={a.article_score} label="Article likelihood" />
              </dd>
            </dl>
            <table className="table table-compact">
              <caption className="sr-only">Where each field came from</caption>
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Taken from</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(sources).map(([field, method]) => (
                  <tr key={field}>
                    <td>{FIELD_LABELS[field] ?? field}</td>
                    <td>{METHOD_LABELS[method] ?? method}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="button-row">
              {can('editor') && (
                <Link className="btn btn-quiet btn-small" to={`/debug?url=${encodeURIComponent(a.url)}`}>
                  Re-run extraction
                </Link>
              )}
              <button type="button" className="btn btn-quiet btn-small" onClick={() => raw.mutate()} disabled={raw.isPending}>
                View raw HTML
              </button>
            </div>
          </section>
          {dupes.data && dupes.data.length > 0 && (
            <section>
              <h2 className="section-title">Copies elsewhere</h2>
              <ul className="plain-list">
                {dupes.data.map((d) => (
                  <li key={d.id}>
                    <Link to={`/articles/${d.id}`}>{d.site_name ?? d.canonical_url}</Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
      </div>
    </article>
  )
}
