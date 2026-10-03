// Mirrors the backend's Pydantic schemas (app/schemas.py).

export type RoleName = 'viewer' | 'editor' | 'admin'

export interface WorkspaceSummary {
  id: number
  name: string
  role: RoleName
  owned: boolean
}

export interface Me {
  email: string | null
  via: 'user' | 'api_key' | 'open'
  workspaces: WorkspaceSummary[]
}

export interface WorkspaceLimits {
  max_sources: number
  max_pages_per_day: number
  max_pages_per_crawl: number
  min_crawl_interval_minutes: number
  max_concurrent_crawls: number
  llm_calls_per_day: number
  max_members: number
}

export interface WorkspaceUsage {
  workspace: WorkspaceSummary
  limits: WorkspaceLimits
  today: { pages: number; llm_calls: number; crawls: number }
  counts: { sources: number; members: number; active_crawls: number }
}

export interface Member {
  id: number
  email: string
  role: RoleName
  joined: boolean
  invited_by: string | null
  last_seen_at: string | null
  created_at: string
}

export type RenderMode = 'never' | 'auto' | 'always'
export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface Paginated<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Source {
  id: number
  name: string
  base_url: string
  domain: string
  allowed_domains: string[]
  start_urls: string[]
  feed_urls: string[]
  sitemap_urls: string[]
  include_patterns: string[]
  exclude_patterns: string[]
  enabled: boolean
  crawl_interval_minutes: number
  max_pages: number
  max_depth: number
  min_delay_seconds: number
  render_mode: RenderMode
  store_raw_html: boolean
  discover_links: boolean
  last_crawl_at: string | null
  next_crawl_at: string | null
  created_at: string
  updated_at: string
}

export type SourceInput = Omit<
  Source,
  'id' | 'domain' | 'last_crawl_at' | 'next_crawl_at' | 'created_at' | 'updated_at' | 'allowed_domains'
> & { allowed_domains: string[] | null }

export interface CrawlStats {
  pages_fetched?: number
  seed_fetches?: number
  pages_failed?: number
  pages_skipped?: number
  not_modified?: number
  robots_blocked?: number
  rendered?: number
  discovered?: number
  hosts_unreachable?: string[]
  stopped_reason?: string | null
  errors?: string[]
}

export interface CrawlJob {
  id: number
  source_id: number
  status: JobStatus
  trigger: string
  triggered_by: string | null
  task_id: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  pages_fetched: number
  pages_failed: number
  pages_skipped: number
  articles_found: number
  articles_new: number
  articles_updated: number
  duplicates: number
  error: string | null
  stats: CrawlStats
}

export interface ArticleSummary {
  id: number
  source_id: number | null
  url: string
  canonical_url: string
  title: string | null
  description: string | null
  authors: string[]
  published_at: string | null
  modified_at: string | null
  image_url: string | null
  category: string | null
  tags: string[]
  language: string | null
  site_name: string | null
  word_count: number
  extraction_method: string | null
  confidence: number
  article_score: number
  duplicate_of_id: number | null
  created_at: string
  updated_at: string
  score: number | null
}

export interface ArticleDetail extends ArticleSummary {
  body: string | null
  content_hash: string | null
  extra: { field_sources?: Record<string, string>; external_canonical?: string; simhash_distance?: number }
}

export interface ArticlePage extends Paginated<ArticleSummary> {
  backend: string
}

export interface Stats {
  generated_at: string
  totals: { sources: number; sources_enabled: number; articles: number; duplicates: number; jobs_active: number }
  last_24h: {
    discovered: number
    fetched: number
    articles: number
    new: number
    duplicates: number
    failed: number
    robots_blocked: number
  }
  articles_per_day: { date: string; count: number }[]
  languages: { language: string; count: number }[]
  jobs_by_status: Partial<Record<JobStatus, number>>
  sources: {
    id: number
    name: string
    enabled: boolean
    articles: number
    last_crawl_at: string | null
    next_crawl_at: string | null
    last_status: JobStatus | null
  }[]
}

export interface Readiness {
  status: 'ok' | 'degraded'
  checks: Record<string, string>
}

export interface StrategyTrace {
  strategy: string
  duration_ms: number
  error: string | null
  signals: Record<string, unknown>
  fields: Record<string, { confidence: number; value: unknown }>
}

export interface ExtractionTrace {
  article: {
    url: string
    canonical_url: string
    title: string | null
    body: string | null
    authors: string[]
    published_at: string | null
    modified_at: string | null
    description: string | null
    image_url: string | null
    category: string | null
    tags: string[]
    language: string | null
    site_name: string | null
    word_count: number
    confidence: number
    article_score: number
    is_article: boolean
    primary_method: string | null
    field_sources: Record<string, string>
    noindex: boolean
    nofollow: boolean
    external_canonical: string | null
  }
  classification: { is_article: boolean; score: number; reasons: string[] }
  used_fallback: boolean
  duration_ms: number
  strategies: StrategyTrace[]
  fetch: {
    status_code?: number
    final_url?: string
    redirects?: string[]
    content_type?: string
    bytes?: number
    attempts?: number
    elapsed_ms?: number
    rendered?: boolean
  }
  fingerprints: { content_hash: string | null; simhash: string | null }
  discovery: { feeds: string[]; links: string[] }
}

export interface ArticleQuery {
  q?: string
  source_id?: number
  language?: string
  category?: string
  since?: string
  until?: string
  min_confidence?: number
  include_duplicates?: boolean
  sort?: 'published' | 'relevance' | 'created'
  limit?: number
  offset?: number
}
