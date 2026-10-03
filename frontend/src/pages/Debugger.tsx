import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime, fmtNumber, languageName } from '../lib/format'
import type { ExtractionTrace } from '../lib/types'
import { EmptyState, ErrorNotice, ExternalLink, Meter, PageHeader } from '../components/ui'

const STRATEGY_LABELS: Record<string, string> = {
  jsonld: 'Structured data (JSON-LD)',
  metatags: 'Page metadata',
  trafilatura: 'Main-text extractor',
  density: 'Text density',
  llm: 'LLM fallback',
}
const FIELDS = ['title', 'authors', 'published_at', 'modified_at', 'description', 'category', 'tags', 'language', 'site_name', 'canonical_url', 'image_url', 'body'] as const
const FIELD_LABELS: Record<string, string> = {
  title: 'Headline',
  authors: 'Authors',
  published_at: 'Published',
  modified_at: 'Updated',
  description: 'Summary',
  category: 'Section',
  tags: 'Tags',
  language: 'Language',
  site_name: 'Publication',
  canonical_url: 'Canonical URL',
  image_url: 'Image',
  body: 'Body',
}

function show(value: unknown): string {
  if (value == null || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) return fmtDateTime(value)
  return String(value)
}

function Verdict({ t }: { t: ExtractionTrace }) {
  const a = t.article
  return (
    <section className={`verdict ${a.is_article ? 'is-article' : 'not-article'}`} aria-live="polite">
      <div>
        <p className="verdict-label">{a.is_article ? 'This page is an article' : 'This page is not treated as an article'}</p>
        <p className="muted">
          Took {Math.round(t.duration_ms)} ms
          {t.used_fallback ? ', including the LLM fallback.' : '.'} {a.word_count > 0 && `${fmtNumber(a.word_count)} words of body text.`}
        </p>
      </div>
      <dl className="verdict-scores">
        <div>
          <dt>Article likelihood</dt>
          <dd>
            <Meter value={t.classification.score} label="Article likelihood" />
          </dd>
        </div>
        <div>
          <dt>Extraction confidence</dt>
          <dd>
            <Meter value={a.confidence} label="Extraction confidence" />
          </dd>
        </div>
      </dl>
    </section>
  )
}

function Result({ t }: { t: ExtractionTrace }) {
  const a = t.article
  return (
    <div className="debug-result">
      <Verdict t={t} />

      <section aria-labelledby="fields-title">
        <h2 id="fields-title" className="section-title">
          Extracted fields
        </h2>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Value</th>
                <th scope="col">Taken from</th>
              </tr>
            </thead>
            <tbody>
              {FIELDS.map((f) => (
                <tr key={f}>
                  <th scope="row">{FIELD_LABELS[f]}</th>
                  <td className={f === 'body' ? 'cell-body' : 'cell-value'}>
                    {f === 'language' ? languageName(a.language) : f === 'body' ? (a.body ? `${a.body.slice(0, 600)}${a.body.length > 600 ? '…' : ''}` : '—') : show(a[f])}
                  </td>
                  <td>{a.field_sources[f] ? STRATEGY_LABELS[a.field_sources[f]] ?? a.field_sources[f] : <span className="muted">Not found</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {a.external_canonical && (
          <p className="notice notice-warning">
            The page claims its canonical address is on another site ({a.external_canonical}). Newsforge ignores it so one site
            can't overwrite another's stories.
          </p>
        )}
      </section>

      <section aria-labelledby="reasons-title">
        <h2 id="reasons-title" className="section-title">
          Why it was scored this way
        </h2>
        <ul className="reasons">
          {t.classification.reasons.map((r) => {
            const m = r.match(/^([+-]\d+\.\d+)\s+(.*)$/)
            const veto = r.startsWith('veto:')
            return (
              <li key={r} className={veto ? 'is-veto' : m && m[1].startsWith('-') ? 'is-neg' : 'is-pos'}>
                <span className="reason-weight">{veto ? 'Veto' : m?.[1]}</span>
                <span>{veto ? r.replace(/^veto:\s*/, '') : (m?.[2] ?? r)}</span>
              </li>
            )
          })}
        </ul>
      </section>

      <section aria-labelledby="strategies-title">
        <h2 id="strategies-title" className="section-title">
          What each method found
        </h2>
        <p className="muted">Each field keeps the candidate with the highest confidence. Methods run from most to least reliable.</p>
        <div className="strategies">
          {t.strategies.map((s) => (
            <details key={s.strategy} className="strategy" open={s.strategy === 'llm'}>
              <summary>
                <span className="strong">{STRATEGY_LABELS[s.strategy] ?? s.strategy}</span>
                <span className="muted">
                  {Object.keys(s.fields).length} fields in {Math.round(s.duration_ms)} ms
                </span>
                {s.error && <span className="tag tag-bad">Error</span>}
              </summary>
              {s.error && <p className="field-error">{s.error}</p>}
              {Object.keys(s.fields).length === 0 && !s.error && <p className="muted">Found nothing on this page.</p>}
              <dl className="facts">
                {Object.entries(s.fields).map(([field, c]) => (
                  <div key={field} className="fact-row">
                    <dt>
                      {FIELD_LABELS[field] ?? field}
                      <span className="muted small"> {Math.round(c.confidence * 100)}%</span>
                    </dt>
                    <dd className={a.field_sources[field] === s.strategy ? 'is-chosen' : undefined}>{show(c.value)}</dd>
                  </div>
                ))}
              </dl>
            </details>
          ))}
        </div>
      </section>

      <section aria-labelledby="fetch-title" className="debug-columns">
        <div>
          <h2 id="fetch-title" className="section-title">
            Fetch
          </h2>
          {t.fetch.status_code || t.fetch.rendered ? (
            <dl className="facts">
              {t.fetch.status_code && (
                <>
                  <dt>Response</dt>
                  <dd>
                    HTTP {t.fetch.status_code}, {fmtNumber(t.fetch.bytes ?? 0)} bytes in {Math.round(t.fetch.elapsed_ms ?? 0)} ms
                  </dd>
                </>
              )}
              {t.fetch.rendered && (
                <>
                  <dt>Rendering</dt>
                  <dd>Rendered in a headless browser</dd>
                </>
              )}
              {t.fetch.redirects && t.fetch.redirects.length > 0 && (
                <>
                  <dt>Redirects</dt>
                  <dd>{t.fetch.redirects.length}</dd>
                </>
              )}
              {t.fetch.final_url && (
                <>
                  <dt>Final URL</dt>
                  <dd className="url-line">{t.fetch.final_url}</dd>
                </>
              )}
            </dl>
          ) : (
            <p className="muted">Extracted from the HTML you pasted.</p>
          )}
          <dl className="facts">
            <dt>Content hash</dt>
            <dd className="url-line">{t.fingerprints.content_hash ?? '—'}</dd>
            <dt>SimHash</dt>
            <dd className="url-line">{t.fingerprints.simhash ?? '—'}</dd>
          </dl>
        </div>
        <div>
          <h2 className="section-title">Discovered on the page</h2>
          {t.discovery.feeds.length > 0 && (
            <>
              <p className="strong">Feeds</p>
              <ul className="plain-list">
                {t.discovery.feeds.map((f) => (
                  <li key={f} className="url-line">
                    {f}
                  </li>
                ))}
              </ul>
            </>
          )}
          <details>
            <summary>{t.discovery.links.length} links</summary>
            <ul className="plain-list link-dump">
              {t.discovery.links.map((l) => (
                <li key={l}>
                  <ExternalLink href={l}>{l}</ExternalLink>
                </li>
              ))}
            </ul>
          </details>
        </div>
      </section>
    </div>
  )
}

export function Debugger() {
  const [params] = useSearchParams()
  const [url, setUrl] = useState(params.get('url') ?? '')
  const [mode, setMode] = useState<'fetch' | 'paste'>('fetch')
  const [html, setHtml] = useState('')
  const [useLlm, setUseLlm] = useState(false)
  const [render, setRender] = useState(false)
  const run = useMutation({ mutationFn: api.extract })
  const { can } = useAuth()
  if (!can('editor')) {
    return <EmptyState title="Editors only">The debugger fetches live pages, so it needs the editor role. Ask an admin if you need it.</EmptyState>
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    run.mutate({
      url: url.trim(),
      html: mode === 'paste' ? html : undefined,
      use_llm: useLlm,
      render: mode === 'fetch' && render,
    })
  }

  return (
    <>
      <PageHeader
        title="Extraction debugger"
        intro="Run the full extraction pipeline on one page and see what each method found, which values won, and why the page was or wasn't treated as an article. Nothing is saved."
      />
      <form className="debug-form" onSubmit={submit}>
        <div className="segmented" role="group" aria-label="Input">
          <button type="button" aria-pressed={mode === 'fetch'} onClick={() => setMode('fetch')}>
            Fetch a URL
          </button>
          <button type="button" aria-pressed={mode === 'paste'} onClick={() => setMode('paste')}>
            Paste HTML
          </button>
        </div>
        <div className="field">
          <label htmlFor="dbg-url">Page URL</label>
          <input
            id="dbg-url"
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.example.com/2026/10/03/story"
          />
          {mode === 'paste' && <p className="field-hint">Used to resolve relative links and judge the URL shape.</p>}
        </div>
        {mode === 'paste' && (
          <div className="field">
            <label htmlFor="dbg-html">HTML</label>
            <textarea id="dbg-html" required rows={8} value={html} onChange={(e) => setHtml(e.target.value)} spellCheck={false} />
          </div>
        )}
        <div className="checks">
          <label className="check">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            Allow the LLM fallback when confidence is low
          </label>
          {mode === 'fetch' && (
            <label className="check">
              <input type="checkbox" checked={render} onChange={(e) => setRender(e.target.checked)} />
              Render in a headless browser
            </label>
          )}
        </div>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={run.isPending}>
            {run.isPending ? 'Extracting…' : 'Run extraction'}
          </button>
          {url && (
            <ExternalLink href={url}>Open the page</ExternalLink>
          )}
        </div>
      </form>
      {run.error && <ErrorNotice error={run.error} />}
      {run.data && <Result t={run.data} />}
    </>
  )
}
