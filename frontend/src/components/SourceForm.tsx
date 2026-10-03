import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../lib/api'
import type { RenderMode, Source, SourceInput } from '../lib/types'
import { useToast } from './toast'

const lines = (v: string) =>
  v
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)

interface FormState {
  name: string
  base_url: string
  feed_urls: string
  sitemap_urls: string
  start_urls: string
  allowed_domains: string
  include_patterns: string
  exclude_patterns: string
  crawl_interval_minutes: string
  max_pages: string
  max_depth: string
  min_delay_seconds: string
  render_mode: RenderMode
  store_raw_html: boolean
  discover_links: boolean
  enabled: boolean
}

function toForm(s?: Source): FormState {
  return {
    name: s?.name ?? '',
    base_url: s?.base_url ?? '',
    feed_urls: s?.feed_urls.join('\n') ?? '',
    sitemap_urls: s?.sitemap_urls.join('\n') ?? '',
    start_urls: s?.start_urls.join('\n') ?? '',
    allowed_domains: s?.allowed_domains.join('\n') ?? '',
    include_patterns: s?.include_patterns.join('\n') ?? '',
    exclude_patterns: s?.exclude_patterns.join('\n') ?? '',
    crawl_interval_minutes: String(s?.crawl_interval_minutes ?? 60),
    max_pages: String(s?.max_pages ?? 200),
    max_depth: String(s?.max_depth ?? 3),
    min_delay_seconds: String(s?.min_delay_seconds ?? 1),
    render_mode: s?.render_mode ?? 'auto',
    store_raw_html: s?.store_raw_html ?? false,
    discover_links: s?.discover_links ?? true,
    enabled: s?.enabled ?? true,
  }
}

function toPayload(f: FormState): Partial<SourceInput> {
  const domains = lines(f.allowed_domains)
  return {
    name: f.name.trim(),
    base_url: f.base_url.trim(),
    feed_urls: lines(f.feed_urls),
    sitemap_urls: lines(f.sitemap_urls),
    start_urls: lines(f.start_urls),
    allowed_domains: domains.length ? domains : null,
    include_patterns: lines(f.include_patterns),
    exclude_patterns: lines(f.exclude_patterns),
    crawl_interval_minutes: Number(f.crawl_interval_minutes),
    max_pages: Number(f.max_pages),
    max_depth: Number(f.max_depth),
    min_delay_seconds: Number(f.min_delay_seconds),
    render_mode: f.render_mode,
    store_raw_html: f.store_raw_html,
    discover_links: f.discover_links,
    enabled: f.enabled,
  }
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string
  label: string
  hint?: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className={`field ${error ? 'has-error' : ''}`}>
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && !error && (
        <p className="field-hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  )
}

export function SourceForm({ source, onDone }: { source?: Source; onDone: (s: Source) => void }) {
  const [form, setForm] = useState<FormState>(() => toForm(source))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const notify = useToast()

  const mutation = useMutation({
    mutationFn: (payload: Partial<SourceInput>) =>
      source ? api.updateSource(source.id, payload) : api.createSource(payload),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      queryClient.invalidateQueries({ queryKey: ['source', saved.id] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      notify(source ? `Saved ${saved.name}` : `Added ${saved.name}`)
      onDone(saved)
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors)
        setFormError(Object.keys(err.fieldErrors).length ? 'Fix the highlighted fields and save again.' : err.message)
      } else {
        setFormError('Could not save the source.')
      }
    },
  })

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }))
  const text = (key: keyof FormState) => ({
    id: `src-${key}`,
    value: form[key] as string,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => set(key, e.target.value as never),
    'aria-invalid': errors[key] ? true : undefined,
    'aria-describedby': errors[key] ? `src-${key}-error` : `src-${key}-hint`,
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setErrors({})
    setFormError(null)
    mutation.mutate(toPayload(form))
  }

  return (
    <form onSubmit={submit} className="form" noValidate>
      {formError && (
        <p className="notice notice-error" role="alert">
          {formError}
        </p>
      )}
      <fieldset>
        <legend>Site</legend>
        <div className="form-row">
          <Field id="src-name" label="Name" error={errors.name}>
            <input {...text('name')} required maxLength={200} autoComplete="off" placeholder="The Guardian" />
          </Field>
          <Field id="src-base_url" label="Homepage URL" error={errors.base_url}>
            <input {...text('base_url')} type="url" required placeholder="https://www.example.com/" />
          </Field>
        </div>
        <Field
          id="src-feed_urls"
          label="RSS or Atom feeds"
          hint="One URL per line. Leave empty to discover feeds and sitemaps automatically."
          error={errors.feed_urls}
        >
          <textarea {...text('feed_urls')} rows={2} />
        </Field>
        <Field id="src-sitemap_urls" label="Sitemaps" hint="One URL per line. Optional." error={errors.sitemap_urls}>
          <textarea {...text('sitemap_urls')} rows={2} />
        </Field>
      </fieldset>

      <fieldset>
        <legend>Schedule and limits</legend>
        <div className="form-row form-row-4">
          <Field id="src-crawl_interval_minutes" label="Crawl every (minutes)" error={errors.crawl_interval_minutes}>
            <input {...text('crawl_interval_minutes')} type="number" min={5} max={10080} />
          </Field>
          <Field id="src-max_pages" label="Pages per crawl" error={errors.max_pages}>
            <input {...text('max_pages')} type="number" min={1} max={20000} />
          </Field>
          <Field id="src-max_depth" label="Link depth" error={errors.max_depth}>
            <input {...text('max_depth')} type="number" min={0} max={10} />
          </Field>
          <Field id="src-min_delay_seconds" label="Delay between requests (s)" error={errors.min_delay_seconds}>
            <input {...text('min_delay_seconds')} type="number" min={0} max={120} step={0.5} />
          </Field>
        </div>
        <div className="checks">
          <label className="check">
            <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} />
            Crawl on schedule
          </label>
          <label className="check">
            <input type="checkbox" checked={form.discover_links} onChange={(e) => set('discover_links', e.target.checked)} />
            Follow links on pages
          </label>
          <label className="check">
            <input type="checkbox" checked={form.store_raw_html} onChange={(e) => set('store_raw_html', e.target.checked)} />
            Keep a copy of the raw HTML
          </label>
        </div>
      </fieldset>

      <details className="advanced">
        <summary>Advanced</summary>
        <Field id="src-render_mode" label="JavaScript rendering" error={errors.render_mode}>
          <select id="src-render_mode" value={form.render_mode} onChange={(e) => set('render_mode', e.target.value as RenderMode)}>
            <option value="auto">When a page looks JavaScript-built</option>
            <option value="always">Always render pages in a browser</option>
            <option value="never">Never</option>
          </select>
        </Field>
        <Field
          id="src-allowed_domains"
          label="Allowed domains"
          hint="One per line. Subdomains are included. Defaults to the homepage's domain."
          error={errors.allowed_domains}
        >
          <textarea {...text('allowed_domains')} rows={2} />
        </Field>
        <Field id="src-start_urls" label="Start pages" hint="One URL per line. Defaults to the homepage." error={errors.start_urls}>
          <textarea {...text('start_urls')} rows={2} />
        </Field>
        <div className="form-row">
          <Field id="src-include_patterns" label="Only article URLs matching" hint="Regular expressions, one per line." error={errors.include_patterns}>
            <textarea {...text('include_patterns')} rows={2} />
          </Field>
          <Field id="src-exclude_patterns" label="Skip URLs matching" hint="Regular expressions, one per line." error={errors.exclude_patterns}>
            <textarea {...text('exclude_patterns')} rows={2} />
          </Field>
        </div>
      </details>

      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving…' : source ? 'Save changes' : 'Add source'}
        </button>
      </div>
    </form>
  )
}
