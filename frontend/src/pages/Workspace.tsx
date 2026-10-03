import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtNumber, intervalLabel } from '../lib/format'
import { useToast } from '../components/toast'
import { Dialog, ErrorNotice, PageHeader, Spinner } from '../components/ui'

function UsageItem({ label, used, limit, note }: { label: string; used: number; limit: number; note?: string }) {
  const ratio = limit > 0 ? Math.min(1, used / limit) : 1
  const level = ratio >= 1 ? 'is-full' : ratio >= 0.8 ? 'is-high' : ''
  return (
    <div className="usage-item">
      <dt>{label}</dt>
      <dd>
        <span className="usage-numbers">
          {fmtNumber(used)} <span className="muted">of {fmtNumber(limit)}</span>
        </span>
        <div
          className={`usage-bar ${level}`}
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={used}
        >
          <span style={{ width: `${ratio * 100}%` }} />
        </div>
        {note && <p className="field-hint">{note}</p>}
      </dd>
    </div>
  )
}

export function WorkspacePage() {
  const { can, refreshWorkspaces, workspaces, switchWorkspace } = useAuth()
  const notify = useToast()
  const navigate = useNavigate()
  const usage = useQuery({ queryKey: ['workspace'], queryFn: api.workspace, refetchInterval: 30_000 })
  const [name, setName] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmName, setConfirmName] = useState('')

  const rename = useMutation({
    mutationFn: (n: string) => api.renameWorkspace(n),
    onSuccess: async (ws) => {
      await refreshWorkspaces()
      await usage.refetch()
      setName(null)
      notify(`Renamed to ${ws.name}`)
    },
    onError: (e) => notify(e instanceof Error ? e.message : 'Could not rename the workspace.', 'error'),
  })
  const remove = useMutation({
    mutationFn: (n: string) => api.deleteWorkspace(n),
    onSuccess: async () => {
      const deleted = usage.data?.workspace.id
      const next = workspaces.find((w) => w.id !== deleted)
      if (next) switchWorkspace(next.id)
      await refreshWorkspaces()
      notify('Workspace deleted')
      navigate('/')
    },
    onError: (e) => notify(e instanceof Error ? e.message : 'Could not delete the workspace.', 'error'),
  })

  if (usage.isPending) return <Spinner />
  if (usage.error) return <ErrorNotice error={usage.error} onRetry={usage.refetch} />
  const { workspace, limits, today, counts } = usage.data
  const isAdmin = can('admin')

  const submitRename = (e: FormEvent) => {
    e.preventDefault()
    if (name?.trim()) rename.mutate(name)
  }

  return (
    <>
      <PageHeader
        title={workspace.name}
        intro={`You’re ${workspace.role === 'admin' ? 'an' : 'a'} ${workspace.role} here. Usage resets every day at midnight UTC.`}
      />

      <section aria-labelledby="usage-title">
        <h2 id="usage-title" className="section-title">
          Today’s usage
        </h2>
        <dl className="usage-grid">
          <UsageItem label="Page fetches" used={today.pages} limit={limits.max_pages_per_day} note="Crawls, feeds, sitemaps and the debugger" />
          <UsageItem label="LLM extractions" used={today.llm_calls} limit={limits.llm_calls_per_day} note="Used only when normal extraction isn’t confident" />
          <UsageItem label="Crawls running" used={counts.active_crawls} limit={limits.max_concurrent_crawls} />
        </dl>
      </section>

      <section aria-labelledby="size-title">
        <h2 id="size-title" className="section-title">
          Workspace size
        </h2>
        <dl className="usage-grid">
          <UsageItem label="Sources" used={counts.sources} limit={limits.max_sources} />
          <UsageItem label="Members" used={counts.members} limit={limits.max_members} />
        </dl>
        <p className="muted small" style={{ marginTop: 'var(--space-3)' }}>
          Each source can crawl up to {fmtNumber(limits.max_pages_per_crawl)} pages per run, and at most{' '}
          {intervalLabel(limits.min_crawl_interval_minutes).toLowerCase()}.
        </p>
      </section>

      {isAdmin && (
        <section aria-labelledby="rename-title">
          <h2 id="rename-title" className="section-title">
            Name
          </h2>
          <form className="inline-form" onSubmit={submitRename}>
            <label htmlFor="ws-rename" className="sr-only">
              Workspace name
            </label>
            <input id="ws-rename" maxLength={100} value={name ?? workspace.name} onChange={(e) => setName(e.target.value)} />
            <button type="submit" className="btn btn-quiet" disabled={rename.isPending || !name || name.trim() === workspace.name}>
              Save name
            </button>
          </form>
        </section>
      )}

      {isAdmin && (
        <section className="danger-zone" aria-labelledby="danger-title">
          <h2 id="danger-title" className="section-title">
            Delete this workspace
          </h2>
          <p>Permanently deletes its sources, crawl history, articles and team. This can’t be undone.</p>
          <div className="button-row">
            <button type="button" className="btn btn-danger-quiet" onClick={() => setConfirmOpen(true)}>
              Delete workspace
            </button>
          </div>
        </section>
      )}

      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)} title={`Delete ${workspace.name}?`}>
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault()
            remove.mutate(confirmName)
          }}
        >
          <p>
            Everything in this workspace is deleted for everyone in it. Type <strong>{workspace.name}</strong> to confirm.
          </p>
          <div className="field">
            <label htmlFor="ws-confirm">Workspace name</label>
            <input id="ws-confirm" autoComplete="off" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
          </div>
          <div className="form-actions">
            <button type="button" className="btn btn-quiet" onClick={() => setConfirmOpen(false)}>
              Keep workspace
            </button>
            <button type="submit" className="btn btn-danger" disabled={remove.isPending || confirmName !== workspace.name}>
              {remove.isPending ? 'Deleting…' : 'Delete workspace'}
            </button>
          </div>
        </form>
      </Dialog>
    </>
  )
}
