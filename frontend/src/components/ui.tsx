import { useEffect, useRef, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { fmtPercent } from '../lib/format'
import type { JobStatus } from '../lib/types'
import { IconCheck, IconClock, IconMinus, IconSpinner, IconWarning, IconX } from './icons'

export function PageHeader({ title, intro, actions }: { title: string; intro?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {intro && <p className="page-intro">{intro}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}

const STATUS: Record<JobStatus, { label: string; icon: ReactNode }> = {
  pending: { label: 'Queued', icon: <IconClock size={14} /> },
  running: { label: 'Running', icon: <IconSpinner size={14} /> },
  succeeded: { label: 'Succeeded', icon: <IconCheck size={14} /> },
  failed: { label: 'Failed', icon: <IconX size={14} /> },
  cancelled: { label: 'Cancelled', icon: <IconMinus size={14} /> },
}

/** Job state: always icon + text, never colour alone. */
export function StatusBadge({ status }: { status: JobStatus }) {
  const s = STATUS[status] ?? { label: status, icon: null }
  return (
    <span className={`status status-${status}`}>
      {s.icon}
      {s.label}
    </span>
  )
}

/** A 0–1 score as a short bar plus its percentage. */
export function Meter({ value, label }: { value: number; label: string }) {
  const level = value >= 0.75 ? 'high' : value >= 0.5 ? 'mid' : 'low'
  return (
    <span className={`meter meter-${level}`} role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={value} aria-label={label}>
      <span className="meter-track">
        <span className="meter-fill" style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="meter-value">{fmtPercent(value)}</span>
    </span>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <IconSpinner size={20} />
      <span>{label}…</span>
    </div>
  )
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError ? error.message : error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div className="notice notice-error" role="alert">
      <IconWarning size={18} />
      <div>
        <p>{message}</p>
        {onRetry && (
          <button type="button" className="btn btn-quiet btn-small" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
}) {
  if (total <= limit) return null
  const page = Math.floor(offset / limit) + 1
  const pages = Math.ceil(total / limit)
  return (
    <nav className="pagination" aria-label="Pagination">
      <button type="button" className="btn btn-quiet btn-small" disabled={page <= 1} onClick={() => onChange(offset - limit)}>
        Previous
      </button>
      <span>
        Page {page} of {pages}
      </span>
      <button
        type="button"
        className="btn btn-quiet btn-small"
        disabled={page >= pages}
        onClick={() => onChange(offset + limit)}
      >
        Next
      </button>
    </nav>
  )
}

/** Native <dialog>: focus trapping, Esc to close and inert background come for free. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  wide?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal?.()
    if (!open && el.open) el.close?.()
  }, [open])
  return (
    <dialog
      ref={ref}
      className={`dialog ${wide ? 'dialog-wide' : ''}`}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      aria-labelledby="dialog-title"
    >
      {open && (
        <>
          <header className="dialog-header">
            <h2 id="dialog-title">{title}</h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
              <IconX />
            </button>
          </header>
          <div className="dialog-body">{children}</div>
        </>
      )}
    </dialog>
  )
}

export function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="ext-link">
      {children}
    </a>
  )
}

export function SourceLink({ id, names }: { id: number | null; names: Map<number, string> }) {
  if (id == null) return <span className="muted">—</span>
  return <Link to={`/sources/${id}`}>{names.get(id) ?? `Source ${id}`}</Link>
}
