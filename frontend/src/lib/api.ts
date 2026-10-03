import { supabase } from './supabase'
import type {
  ArticleDetail,
  ArticlePage,
  ArticleQuery,
  ArticleSummary,
  CrawlJob,
  ExtractionTrace,
  Me,
  Member,
  Paginated,
  RoleName,
  Readiness,
  Source,
  SourceInput,
  Stats,
} from './types'

// Empty means same origin (the nginx container proxies /api to the backend).
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const KEY_STORAGE = 'newsforge.apiKey'

export class ApiError extends Error {
  status: number
  fieldErrors: Record<string, string>

  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message)
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

// --- API key storage -------------------------------------------------------------
// Session storage by default (cleared when the browser closes); local storage only
// when the user asks to stay signed in on this device.

function safeGet(store: () => Storage, key: string): string | null {
  try {
    return store().getItem(key)
  } catch {
    return null
  }
}

export function getStoredKey(): string | null {
  return safeGet(() => sessionStorage, KEY_STORAGE) ?? safeGet(() => localStorage, KEY_STORAGE)
}

export function storeKey(key: string, remember: boolean): void {
  clearKey()
  try {
    ;(remember ? localStorage : sessionStorage).setItem(KEY_STORAGE, key)
  } catch {
    /* storage unavailable: the key lives only in memory for this tab */
  }
}

export function clearKey(): void {
  for (const store of [() => sessionStorage, () => localStorage]) {
    try {
      store().removeItem(KEY_STORAGE)
    } catch {
      /* ignore */
    }
  }
}

let unauthorizedHandler: (() => void) | null = null
export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler
}

// --- request core ----------------------------------------------------------------

type Query = Record<string, string | number | boolean | undefined | null>

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  }
  const qs = params.toString()
  return `${BASE_URL}${path}${qs ? `?${qs}` : ''}`
}

function parseError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: ['body', 'field'], msg: '...'}]
    const fieldErrors: Record<string, string> = {}
    for (const item of detail as { loc?: unknown[]; msg?: string }[]) {
      const field = String(item.loc?.[item.loc.length - 1] ?? 'form')
      fieldErrors[field] = (item.msg ?? 'Invalid value').replace(/^Value error, /, '')
    }
    return new ApiError(status, 'Some fields need attention.', fieldErrors)
  }
  if (typeof detail === 'string') return new ApiError(status, detail)
  if (status === 0) return new ApiError(0, 'Could not reach the Newsforge API. Check your connection and the API address.')
  return new ApiError(status, `The API returned an error (HTTP ${status}).`)
}

export async function request<T>(
  method: string,
  path: string,
  options: { query?: Query; body?: unknown; key?: string; raw?: boolean; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (supabase && !options.key) {
    // Person sign-in: send the current (auto-refreshed) Supabase access token.
    const { data } = await supabase.auth.getSession()
    if (data.session) headers.Authorization = `Bearer ${data.session.access_token}`
  } else {
    const key = options.key ?? getStoredKey()
    if (key) headers['X-API-Key'] = key
  }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw parseError(0, null)
  }

  if (res.status === 401 && !options.key) unauthorizedHandler?.()
  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      /* non-JSON error body */
    }
    throw parseError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  return (options.raw ? res.text() : res.json()) as Promise<T>
}

// --- endpoints -------------------------------------------------------------------

export const api = {
  verifyKey: (key: string) => request<Me>('GET', '/api/v1/me', { key }),
  me: () => request<Me>('GET', '/api/v1/me'),
  members: () => request<Member[]>('GET', '/api/v1/members'),
  inviteMember: (body: { email: string; role: RoleName }) => request<Member>('POST', '/api/v1/members', { body }),
  changeRole: (id: number, role: RoleName) => request<Member>('PATCH', `/api/v1/members/${id}`, { body: { role } }),
  removeMember: (id: number) => request<void>('DELETE', `/api/v1/members/${id}`),
  readiness: () =>
    fetch(buildUrl('/health/ready')).then(async (r) => (await r.json()) as Readiness).catch(
      (): Readiness => ({ status: 'degraded', checks: { api: 'unreachable' } }),
    ),
  stats: (days = 14) => request<Stats>('GET', '/api/v1/stats', { query: { days } }),

  sources: (query: { limit?: number; offset?: number; enabled?: boolean } = {}) =>
    request<Paginated<Source>>('GET', '/api/v1/sources', { query: { limit: 200, ...query } }),
  source: (id: number) => request<Source>('GET', `/api/v1/sources/${id}`),
  createSource: (body: Partial<SourceInput>) => request<Source>('POST', '/api/v1/sources', { body }),
  updateSource: (id: number, body: Partial<SourceInput>) => request<Source>('PATCH', `/api/v1/sources/${id}`, { body }),
  deleteSource: (id: number) => request<void>('DELETE', `/api/v1/sources/${id}`),
  startCrawl: (sourceId: number) => request<CrawlJob>('POST', `/api/v1/sources/${sourceId}/crawl`),

  crawls: (query: { source_id?: number; status?: string; limit?: number; offset?: number } = {}) =>
    request<Paginated<CrawlJob>>('GET', '/api/v1/crawls', { query }),
  crawl: (id: number) => request<CrawlJob>('GET', `/api/v1/crawls/${id}`),
  cancelCrawl: (id: number) => request<CrawlJob>('POST', `/api/v1/crawls/${id}/cancel`),

  articles: (query: ArticleQuery) => request<ArticlePage>('GET', '/api/v1/articles', { query: { ...query } }),
  article: (id: number) => request<ArticleDetail>('GET', `/api/v1/articles/${id}`),
  duplicates: (id: number) => request<ArticleSummary[]>('GET', `/api/v1/articles/${id}/duplicates`),
  rawHtml: (id: number) => request<string>('GET', `/api/v1/articles/${id}/raw`, { raw: true }),

  extract: (body: { url: string; html?: string; render?: boolean; use_llm?: boolean }) =>
    request<ExtractionTrace>('POST', '/api/v1/debug/extract', { body }),
}
