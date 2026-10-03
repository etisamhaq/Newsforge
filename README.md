# Newsforge

Newsforge discovers, extracts, deduplicates and indexes news articles from any number of sources.

- **Discovery**: RSS / Atom / RDF / JSON Feed, XML sitemaps (index, news, gzip), in-page links, plus auto-discovery (`<link rel=alternate>`, `Sitemap:` lines in robots.txt).
- **Polite and safe fetching**: robots.txt (RFC 9309 wildcards, Crawl-delay), per-host rate limits shared across workers through Redis, bounded retries with backoff and capped `Retry-After`, conditional GET (ETag / Last-Modified), size limits, and SSRF protection with connect-time IP pinning.
- **Extraction**: JSON-LD / schema.org first, then OpenGraph / meta tags, then trafilatura and a text-density fallback, then an optional LLM fallback when confidence is low. Playwright renders JavaScript-built pages.
- **Article detection**: a transparent weighted classifier that returns the reasons for its score.
- **Dedup**: canonical URL, then content hash, then SimHash near-duplicates (banded index lookup).
- **Storage and search**: PostgreSQL (raw HTML optional, gzip-compressed). Search uses Postgres full-text search through a pluggable backend.
- **Ops**: FastAPI, Celery worker and beat, structured JSON logs, Prometheus metrics, Alembic migrations, Docker Compose.

## Quick start (Docker)

```bash
cp .env.example .env          # set API_KEY to a strong secret
docker compose up --build -d  # postgres, redis, migrate, api, web, worker, worker-default, beat
curl localhost:8080/health/ready
```

Open **http://localhost:8080** and sign in with your `API_KEY`.

| Service | Purpose |
| --- | --- |
| `web` | The web UI on :8080 (nginx). Also proxies `/api` to the API, so this is the only port browsers need |
| `api` | FastAPI, bound to `127.0.0.1:8000` (`/docs` for OpenAPI) |
| `worker` | Celery worker for the `crawl` queue (Chromium installed). Metrics on :9100 |
| `worker-default` | Runs the scheduler tick (`default` queue) so it never waits behind long crawls |
| `beat` | Fires `dispatch_due` every `SCHEDULER_INTERVAL_SECONDS` |
| `migrate` | `alembic upgrade head`, runs once before the app starts |

## Web UI

`frontend/` is a React + TypeScript app (Vite, TanStack Query, React Router). Plain CSS with design tokens, light and dark themes, and fonts bundled locally so the app makes no third-party requests.

| Screen | What it's for |
| --- | --- |
| Dashboard | Last-24h pipeline (discovered → fetched → articles → new → duplicates), latest stories, daily volume, languages, crawl outcomes, per-source health |
| Sources | Add, edit, pause or delete sources, and start a crawl |
| Crawls | Every run with live progress, results, errors and cancel |
| Articles | Full-text search with filters (source, language, dates, confidence, duplicates), plus a reader view showing where each field came from |
| Extraction debugger | Run the pipeline on any URL or pasted HTML and see every method's output, the winning values and the classifier's reasons |

Sign-in uses the server's `API_KEY`. It's kept in session storage, or in local storage only if "Stay signed in" is ticked.

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxies /api to VITE_DEV_API_TARGET (default http://localhost:8000)
npm test           # unit tests (Vitest)
npm run lint && npm run build
```

## Deploying

The Compose file is the production layout. On a server:

1. Copy `.env.example` to `.env` and set a strong `API_KEY`. Set `GROQ_API_KEY` too if you want the LLM fallback.
2. Run `docker compose up --build -d`.
3. Put your TLS reverse proxy or load balancer in front of the `web` service (port 8080). It's the only service that needs to be public.

`web` serves the built app with strict security headers (CSP, `frame-ancestors 'none'`, nosniff) and proxies `/api` and `/health` to the `api` container. `/metrics` is not exposed through it.

**Hosting the UI separately** (a static host or CDN): build with `VITE_API_BASE_URL=https://api.example.com npm run build`, then set `CORS_ORIGINS=["https://ui.example.com"]` on the API. When using the `web` image with a remote API, set `API_UPSTREAM` to the API's address, and `CSP_CONNECT_SRC` if the browser must call another origin.

## Local development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,llm,browser]"
.venv/bin/playwright install chromium        # optional, only for JS rendering
export DATABASE_URL=postgresql+asyncpg://crawler:crawler@localhost:5432/crawler REDIS_URL=redis://localhost:6379/0
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.api.main:app --reload
.venv/bin/celery -A app.workers.celery_app worker -Q crawl,default
.venv/bin/celery -A app.workers.celery_app beat
```

## Tests

```bash
.venv/bin/pytest                                   # SQLite, no services needed
TEST_DATABASE_URL=postgresql+asyncpg://user@host/crawler_test .venv/bin/pytest   # same suite on Postgres
.venv/bin/ruff check app tests alembic
```

The tests cover: URL normalization, SSRF (IP classes, DNS rebinding at connect time, redirects to private IPs), robots parsing and caching, fetch retries, timeouts, size limits and gzip bombs, conditional GET, feed and sitemap parsing (including XML entity attacks), every extraction strategy, LLM fallback gating (using a fake client), classifier vetoes, dedup layers, full simulated-site crawls (traps, off-site links, robots, budgets, circuit breaker, stale entries), scheduling, the whole REST API, and real Chromium rendering, where the test checks that a page's sub-request to the metadata IP is blocked.

## API

All `/api/v1/*` routes need a signed-in member (`Authorization: Bearer <Supabase access token>`) or the API key (`X-API-Key`). Write endpoints need the editor role, and deleting sources or managing the team needs admin (see [Workspaces, accounts and roles](#workspaces-accounts-and-roles)). `/health`, `/health/ready` and `/metrics` stay open for probes.

```bash
H='X-API-Key: change-me'
# Add a source. Feeds and sitemaps are optional (auto-discovered when omitted).
curl -H "$H" -H 'content-type: application/json' localhost:8000/api/v1/sources -d '{
  "name": "The Guardian", "base_url": "https://www.theguardian.com/international",
  "feed_urls": ["https://www.theguardian.com/world/rss"],
  "max_pages": 100, "max_depth": 2, "min_delay_seconds": 2, "crawl_interval_minutes": 30
}'
curl -X POST -H "$H" localhost:8000/api/v1/sources/1/crawl           # start now (202 + job)
curl -H "$H" localhost:8000/api/v1/crawls/1                           # progress / stats
curl -H "$H" 'localhost:8000/api/v1/articles?q=election&sort=relevance&language=en&since=2026-10-01T00:00:00Z'
curl -H "$H" -H 'content-type: application/json' localhost:8000/api/v1/debug/extract -d '{"url": "https://..."}'
```

| Method & path | Description |
| --- | --- |
| `POST/GET /sources`, `GET/PATCH/DELETE /sources/{id}` | Manage sources (URLs are validated against the SSRF guard; regex patterns are size-limited) |
| `POST /sources/{id}/crawl` | Start a crawl (409 if one is already pending or running) |
| `GET /crawls`, `GET /crawls/{id}`, `POST /crawls/{id}/cancel` | Jobs, stats and cooperative cancel |
| `GET /articles` | List and search: `q`, `source_id`, `language`, `category`, `since`, `until`, `min_confidence`, `include_duplicates`, `sort=published\|relevance\|created` |
| `GET /articles/{id}` / `/duplicates` / `/raw` | Detail with body, linked duplicates, stored raw HTML (served as sandboxed `text/plain`) |
| `GET /me`, `POST /workspaces` | The signed-in person and their workspaces; create a workspace |
| `GET/PATCH/DELETE /workspace` | The current workspace: usage and limits; rename or delete (admin) |
| `GET/POST /members`, `PATCH/DELETE /members/{id}` | Team management in the current workspace (admin) |
| `GET /stats` | Dashboard aggregates: totals, last-24h pipeline, articles per day (UTC), languages, job outcomes, per-source health |
| `POST /debug/extract` | Full extraction trace for a URL or supplied HTML: each strategy's candidates, timings, merged field sources, classifier reasons, fingerprints, discovered links. Options: `render`, `use_llm`, `include_html` |
| `GET /debug/robots?url=`, `GET /debug/normalize?url=` | robots.txt decision and URL normalization |

## Workspaces, accounts and roles

Newsforge is multi-tenant. Each **workspace** is a team's private space with its own sources, crawls, articles and members. Nothing is shared between workspaces: listings, search, stats, duplicate detection and the HTTP page cache are all scoped to one workspace.

- **Signing up:** anyone can create an account (email and password through Supabase Auth). On first sign-in they join every workspace that invited their email. If there were no invitations, they get a new workspace of their own as its admin.
- **Teams:** admins invite people by email from the Team page and pick their role. People in several workspaces switch between them in the sidebar, and can create up to `MAX_OWNED_WORKSPACES` (default 3) of their own.
- **The original workspace:** data that existed before workspaces lives in "Newsforge". Emails in `ADMIN_EMAILS` become its admins.

| Role (per workspace) | Can |
| --- | --- |
| Viewer | Read the dashboard, sources, crawls and articles |
| Editor | Also add and edit sources, start and cancel crawls, and use the extraction debugger |
| Admin | Also delete sources, manage the team, and rename or delete the workspace |

**Limits per workspace.** These are defaults; each `workspaces` row can override them, with NULL meaning "use the default".

| Setting | Default | What it limits |
| --- | --- | --- |
| `WORKSPACE_MAX_SOURCES` | 10 | Sources in the workspace |
| `WORKSPACE_MAX_PAGES_PER_DAY` | 500 | Every network fetch: crawled pages, feeds, sitemaps and the debugger. Crawls stop with "daily limit" |
| `WORKSPACE_MAX_PAGES_PER_CRAWL` | 200 | A source's pages per run |
| `WORKSPACE_MIN_CRAWL_INTERVAL_MINUTES` | 30 | How often a source may be scheduled |
| `WORKSPACE_MAX_CONCURRENT_CRAWLS` | 2 | Crawls running at once |
| `WORKSPACE_LLM_CALLS_PER_DAY` | 25 | LLM fallback extractions |
| `WORKSPACE_MAX_MEMBERS` | 25 | Members, including pending invitations |

Usage resets at midnight UTC and is shown on the Workspace page. Over-limit requests get HTTP 429 with a plain explanation. The scheduler skips a workspace for the round while it's at a limit. Per-site politeness (robots.txt, rate limits) stays global, so two workspaces crawling the same site don't double the load on it.

**How requests are scoped:** the UI sends `X-Workspace-Id` with every request; without it the API uses the person's first workspace. The API verifies Supabase access tokens (ES256) against the project's public JWKS, checking signature, expiry, issuer and audience, so no Supabase secret is stored. `X-API-Key: $API_KEY` still works for automation, as an admin of whichever workspace the request names (default: the original). Without `SUPABASE_URL` and the `VITE_SUPABASE_*` values the UI falls back to API-key sign-in.

**Supabase dashboard settings (one-time):**
- *Authentication → URL Configuration:* set **Site URL** to your web URL, and add it with `/**` under **Redirect URLs**, so confirmation and reset links come back to the app.
- *Authentication → Emails → SMTP:* configure a real email provider (e.g. Resend, Postmark or SES). Supabase's built-in sender only delivers to your Supabase organization's own members and is heavily rate-limited, so invited colleagues won't receive their confirmation emails without it.

## Architecture

```text
app/
  api/            FastAPI app, routes, API-key dependency, request-id + metrics middleware
  crawler/
    security.py   UrlGuard (scheme/port/host/IP checks) + GuardedNetworkBackend (connect-time IP pinning)
    fetcher.py    httpx client: robots, rate limit, retries, redirects (re-checked per hop), size caps, caching
    robots.py     RFC 9309 parser + per-origin TTL cache (single-flight)
    ratelimit.py  Redis (cluster-wide) / in-memory per-host spacing
    discovery.py  feeds, sitemaps, links, article-URL prior
    renderer.py   Playwright fallback (every browser request goes through the SSRF guard)
    engine.py     priority frontier, scope/trap rules, budgets, circuit breaker, per-page pipeline
  extraction/
    base.py       ExtractionStrategy, StrategyRegistry, per-field candidate merging
    jsonld.py, metadata.py, content.py, llm.py   strategies
    classifier.py article detection, pipeline.py orchestration + confidence
  dedup/          content hash, SimHash (+ 4x16-bit bands)
  search/         SearchBackend interface, Postgres FTS + portable LIKE backends
  services/       ArticleRepository (layered dedup upsert), crawl job lifecycle + scheduler
  workers/        Celery app (queues, beat schedule, worker metrics server) and tasks
alembic/          migrations (includes the generated tsvector column + GIN index)
```

### Confidence scores

- `article_score` (0–1): classifier output. Signals include JSON-LD article type, `og:type`, dates, body length, paragraphs, link density and the URL shape. `noindex` pages and bodies under about 30 words are vetoed. `/debug/extract` shows the reasons.
- `confidence` (0–1): weighted completeness × per-field reliability (title 0.2, body 0.35 scaled by length, date 0.15, author 0.1, other fields 0.05 each). When it falls below `LLM_CONFIDENCE_THRESHOLD`, the LLM fallback runs (if enabled).

### Extending

**New extraction strategy:** each field is merged by confidence, and the body is also weighted by length, so a teaser can't beat the full text.

```python
from app.extraction.base import ExtractionStrategy, StrategyResult
from app.extraction.pipeline import default_registry, ExtractionPipeline

class PaywallNoteStrategy(ExtractionStrategy):
    name, priority = "site-x", 15
    async def extract(self, ctx, merged):
        r = StrategyResult(self.name)
        node = ctx.tree.css_first(".headline-x")
        if node: r.add("title", node.text(strip=True), 0.97)
        return r

registry = default_registry(); registry.register(PaywallNoteStrategy())
pipeline = ExtractionPipeline(registry)
```

Set `is_fallback = True` to run a strategy only when confidence stays low, as the LLM strategy does.

**New search backend** (Elasticsearch, OpenSearch, Meilisearch, a vector DB): subclass `SearchBackend`, implement `search()`, and optionally `index()` / `remove()`. The repository calls `index()` after every insert or update. Register it with `register_backend("es", EsBackend)` and set `SEARCH_BACKEND=es`.

**Another LLM provider:** implement the `LLMClient` protocol (`extract_article(url, page_text, metadata)`) and pass it to `LLMStrategy(client)`.

## Safety limits

| Threat | Mitigation |
| --- | --- |
| SSRF | http/https only, no credentials in URLs, port allowlist, internal hostnames rejected, every resolved IP must be public (private, loopback, link-local, CGNAT, reserved, multicast, IPv4-mapped, 6to4 and Teredo are all rejected). Checks run again on each redirect hop and **at connect time** (DNS-rebinding safe). Env proxies are ignored. The browser renderer routes every sub-request through the same guard. |
| Infinite crawling | `max_pages`, `max_depth`, frontier cap, crawl time budget, same-site scope, include/exclude regexes, trap heuristics (repeating segments, deep paths, session IDs, huge page numbers), max feed/sitemap fan-out, stale-entry cutoff (`MAX_ARTICLE_AGE_DAYS`) |
| Oversized responses | `Content-Length` pre-check plus a streaming byte cap. That cap also applies after HTTP decompression. Gzip sitemaps are decompressed with a bounded inflater (bomb-safe). Sitemaps get their own 50 MB limit. XML DTD entities are rejected. |
| Excessive retries | `MAX_RETRIES` cap, exponential backoff with jitter, `Retry-After` honored only up to `MAX_RETRY_AFTER`, per-URL failure count (`MAX_PAGE_FAILURES`), and a per-host circuit breaker after 5 consecutive network failures |
| Concurrency | Redis lock per source (one crawl at a time), `SELECT … FOR UPDATE SKIP LOCKED` in the scheduler, a unique canonical hash with an upsert retry, and a reaper for stale jobs |
| Stored HTML | Served only as `text/plain` with `CSP: sandbox` and `nosniff` |

The crawler does **not** bypass CAPTCHAs, authentication or anti-bot systems. It identifies itself with `USER_AGENT`. Sites that block that agent are recorded as failures or robots denials and skipped.

## LLM fallback (optional)

Set `LLM_ENABLED=true` and choose a provider:

- **Groq (default):** `LLM_PROVIDER=groq` and `GROQ_API_KEY`. Uses `GROQ_MODEL` (default `openai/gpt-oss-120b`) through Groq's OpenAI-compatible API, with JSON-schema constrained output validated by Pydantic. Retries 429/5xx with a bounded `Retry-After`.
- **Anthropic:** `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`. Uses Claude (`LLM_MODEL`) with structured outputs.

The LLM runs only when heuristic confidence is below `LLM_CONFIDENCE_THRESHOLD` and the page looks article-like. Page text over `LLM_MAX_INPUT_CHARS` is truncated (recorded in the strategy signals). Page content goes to the model as untrusted data.

## Metrics

On the API at `/metrics`, and on workers at `:9100` (multiprocess mode):

- `newsforge_fetch_total{outcome,status}`
- `newsforge_fetch_duration_seconds`
- `newsforge_blocked_total{reason=ssrf|robots|oversized}`
- `newsforge_articles_total{outcome=new|updated|unchanged|duplicate|near_duplicate}`
- `newsforge_extraction_confidence`, `newsforge_article_score`
- `newsforge_llm_calls_total`, `newsforge_render_total`
- `newsforge_jobs_total{status}`, `newsforge_job_duration_seconds`, `newsforge_active_jobs`
- `api_requests_total`, `api_request_duration_seconds`

## Configuration

Every setting is an environment variable. See `app/config.py` and `.env.example`. Key settings:

- `DATABASE_URL`, `REDIS_URL`, `API_KEY`, `SUPABASE_URL`, `ADMIN_EMAILS`, `CORS_ORIGINS`, `USER_AGENT`
- `DEFAULT_MIN_DELAY`, `MAX_RETRIES`, `MAX_RESPONSE_BYTES`, `MAX_SITEMAP_BYTES`
- `CRAWL_CONCURRENCY`, `CRAWL_TIME_BUDGET_SECONDS`, `MAX_ARTICLE_AGE_DAYS`
- `PLAYWRIGHT_ENABLED`, `LLM_ENABLED`, `SEARCH_BACKEND`, `SIMHASH_MAX_DISTANCE`

Keep `SIMHASH_MAX_DISTANCE` at 3 or less: with 4 bands, that is what guarantees no candidates are missed.
