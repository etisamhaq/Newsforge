import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtDate, fmtNumber, languageName } from '../lib/format'
import { useSourceNames } from '../lib/hooks'
import type { ArticleQuery } from '../lib/types'
import { EmptyState, ErrorNotice, Meter, PageHeader, Pagination, Spinner } from '../components/ui'

const LIMIT = 20
const LANGS = ['en', 'es', 'fr', 'de', 'ar', 'ur', 'pt', 'it', 'zh', 'ru', 'hi', 'tr']

export function Articles() {
  const [params, setParams] = useSearchParams()
  const names = useSourceNames()

  const query: ArticleQuery = {
    q: params.get('q') || undefined,
    source_id: params.get('source_id') ? Number(params.get('source_id')) : undefined,
    language: params.get('language') || undefined,
    since: params.get('since') ? `${params.get('since')}T00:00:00Z` : undefined,
    until: params.get('until') ? `${params.get('until')}T23:59:59Z` : undefined,
    min_confidence: params.get('min_confidence') ? Number(params.get('min_confidence')) : undefined,
    include_duplicates: params.get('dupes') === '1' || undefined,
    sort: (params.get('sort') as ArticleQuery['sort']) || (params.get('q') ? 'relevance' : 'published'),
    limit: LIMIT,
    offset: Number(params.get('offset') ?? 0),
  }

  const { data, error, refetch, isPending, isFetching } = useQuery({
    queryKey: ['articles', query],
    queryFn: () => api.articles(query),
    placeholderData: keepPreviousData,
  })

  const update = (next: Record<string, string | undefined>) => {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v) p.set(k, v)
      else p.delete(k)
    }
    if (!('offset' in next)) p.delete('offset')
    setParams(p)
  }

  const search = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const q = String(new FormData(e.currentTarget).get('q') ?? '').trim()
    update({ q: q || undefined, sort: q ? 'relevance' : undefined })
  }

  const filtered = ['source_id', 'language', 'since', 'until', 'min_confidence', 'dupes', 'q'].some((k) => params.get(k))

  return (
    <>
      <PageHeader title="Articles" intro={data ? `${fmtNumber(data.total)} matching stories` : undefined} />
      <form className="search" role="search" onSubmit={search}>
        <label htmlFor="article-q" className="sr-only">
          Search articles
        </label>
        <input
          id="article-q"
          name="q"
          type="search"
          key={params.get('q') ?? ''}
          defaultValue={params.get('q') ?? ''}
          placeholder="Search headlines and full text"
          maxLength={500}
        />
        <button type="submit" className="btn btn-primary">
          Search
        </button>
      </form>
      <div className="filters">
        <label>
          Source
          <select value={params.get('source_id') ?? ''} onChange={(e) => update({ source_id: e.target.value || undefined })}>
            <option value="">All sources</option>
            {[...names].map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Language
          <select value={params.get('language') ?? ''} onChange={(e) => update({ language: e.target.value || undefined })}>
            <option value="">Any language</option>
            {LANGS.map((l) => (
              <option key={l} value={l}>
                {languageName(l)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Published from
          <input type="date" value={params.get('since') ?? ''} onChange={(e) => update({ since: e.target.value || undefined })} />
        </label>
        <label>
          Published until
          <input type="date" value={params.get('until') ?? ''} onChange={(e) => update({ until: e.target.value || undefined })} />
        </label>
        <label>
          Confidence
          <select value={params.get('min_confidence') ?? ''} onChange={(e) => update({ min_confidence: e.target.value || undefined })}>
            <option value="">Any</option>
            <option value="0.5">50% or more</option>
            <option value="0.75">75% or more</option>
            <option value="0.9">90% or more</option>
          </select>
        </label>
        <label>
          Sort by
          <select value={query.sort} onChange={(e) => update({ sort: e.target.value })}>
            {query.q && <option value="relevance">Best match</option>}
            <option value="published">Newest published</option>
            <option value="created">Newest collected</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={params.get('dupes') === '1'} onChange={(e) => update({ dupes: e.target.checked ? '1' : undefined })} />
          Include duplicates
        </label>
        {filtered && (
          <button type="button" className="btn btn-quiet btn-small" onClick={() => setParams({})}>
            Clear filters
          </button>
        )}
      </div>

      {isPending && <Spinner />}
      {error && <ErrorNotice error={error} onRetry={refetch} />}
      {data && data.items.length === 0 && (
        <EmptyState title="No articles match">
          {filtered ? 'Try fewer filters or a different search.' : 'Articles appear here once a crawl collects them.'}
        </EmptyState>
      )}
      <ol className={`results ${isFetching && !isPending ? 'is-refreshing' : ''}`}>
        {data?.items.map((a) => (
          <li key={a.id} className="result">
            <div className="result-main">
              <Link to={`/articles/${a.id}`} className="headline">
                {a.title ?? a.url}
              </Link>
              {a.description && <p className="dek">{a.description}</p>}
              <p className="result-meta">
                <span>{a.source_id != null ? names.get(a.source_id) ?? a.site_name : a.site_name}</span>
                <span>{fmtDate(a.published_at)}</span>
                <span>{languageName(a.language)}</span>
                {a.authors.length > 0 && <span>{a.authors.slice(0, 2).join(', ')}</span>}
                {a.duplicate_of_id && <span className="tag">Duplicate</span>}
              </p>
            </div>
            <Meter value={a.confidence} label="Extraction confidence" />
          </li>
        ))}
      </ol>
      {data && (
        <Pagination total={data.total} limit={LIMIT} offset={query.offset ?? 0} onChange={(o) => update({ offset: String(o) })} />
      )}
    </>
  )
}
