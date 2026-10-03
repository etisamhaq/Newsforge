import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtRelative } from '../lib/format'
import type { Member, RoleName } from '../lib/types'
import { useToast } from '../components/toast'
import { Dialog, EmptyState, ErrorNotice, PageHeader, Spinner } from '../components/ui'

const ROLES: { value: RoleName; label: string; does: string }[] = [
  { value: 'viewer', label: 'Viewer', does: 'Reads the dashboard, sources, crawls and articles' },
  { value: 'editor', label: 'Editor', does: 'Also adds and edits sources, runs crawls and uses the debugger' },
  { value: 'admin', label: 'Admin', does: 'Also deletes sources and manages the team' },
]

function InviteForm({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<RoleName>('viewer')
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const notify = useToast()
  const invite = useMutation({
    mutationFn: () => api.inviteMember({ email, role }),
    onSuccess: (m) => {
      queryClient.invalidateQueries({ queryKey: ['members'] })
      notify(`Invited ${m.email}`)
      onDone()
    },
    onError: (err) => setError(err instanceof ApiError ? err.fieldErrors.email ?? err.message : 'Could not send the invitation.'),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    invite.mutate()
  }
  return (
    <form className="form" onSubmit={submit}>
      {error && (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      )}
      <div className="field">
        <label htmlFor="invite-email">Email</label>
        <input id="invite-email" type="email" required autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />
        <p className="field-hint">They create an account with this email, then get access straight away.</p>
      </div>
      <fieldset>
        <legend className="sr-only">Role</legend>
        <div className="role-options">
          {ROLES.map((r) => (
            <label key={r.value} className={`role-option ${role === r.value ? 'is-selected' : ''}`}>
              <input type="radio" name="role" value={r.value} checked={role === r.value} onChange={() => setRole(r.value)} />
              <span>
                <span className="strong">{r.label}</span>
                <span className="sub">{r.does}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={invite.isPending}>
          {invite.isPending ? 'Inviting…' : 'Invite'}
        </button>
      </div>
    </form>
  )
}

function MemberRow({ m, isMe }: { m: Member; isMe: boolean }) {
  const queryClient = useQueryClient()
  const notify = useToast()
  const [confirm, setConfirm] = useState(false)
  const onError = (err: unknown) => notify(err instanceof Error ? err.message : 'That didn’t work.', 'error')
  const change = useMutation({
    mutationFn: (role: RoleName) => api.changeRole(m.id, role),
    onSuccess: (u) => {
      queryClient.invalidateQueries({ queryKey: ['members'] })
      if (isMe) queryClient.invalidateQueries({ queryKey: ['me'] })
      notify(`${u.email} is now ${u.role === 'admin' ? 'an' : 'a'} ${u.role}`)
    },
    onError,
  })
  const remove = useMutation({
    mutationFn: () => api.removeMember(m.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members'] })
      notify(`Removed ${m.email}`)
      setConfirm(false)
    },
    onError,
  })
  return (
    <tr>
      <td>
        <span className="strong">{m.email}</span>
        {isMe && <span className="tag">You</span>}
        <span className="sub">{m.invited_by ? `Invited by ${m.invited_by}` : ''}</span>
      </td>
      <td>
        <label className="sr-only" htmlFor={`role-${m.id}`}>
          Role for {m.email}
        </label>
        <select id={`role-${m.id}`} value={m.role} disabled={change.isPending} onChange={(e) => change.mutate(e.target.value as RoleName)}>
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </td>
      <td>{m.joined ? <span>Active {m.last_seen_at ? fmtRelative(m.last_seen_at) : ''}</span> : <span className="muted">Invited, hasn’t signed in</span>}</td>
      <td className="actions">
        <button type="button" className="btn btn-danger-quiet btn-small" onClick={() => setConfirm(true)}>
          Remove
        </button>
        <Dialog open={confirm} onClose={() => setConfirm(false)} title={`Remove ${m.email}?`}>
          <p>
            {isMe ? 'You will lose access to Newsforge immediately.' : 'They lose access immediately.'} Their Supabase account stays, so you can
            invite them again later.
          </p>
          <div className="form-actions">
            <button type="button" className="btn btn-quiet" onClick={() => setConfirm(false)}>
              Keep
            </button>
            <button type="button" className="btn btn-danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
              {remove.isPending ? 'Removing…' : 'Remove'}
            </button>
          </div>
        </Dialog>
      </td>
    </tr>
  )
}

export function Team() {
  const { can, email } = useAuth()
  const [inviting, setInviting] = useState(false)
  const members = useQuery({ queryKey: ['members'], queryFn: api.members, enabled: can('admin') })

  if (!can('admin')) {
    return <EmptyState title="Admins only">Ask an admin if you need to add someone or change a role.</EmptyState>
  }
  return (
    <>
      <PageHeader
        title="Team"
        intro="People who can use Newsforge and what they can do."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setInviting(true)}>
            Invite someone
          </button>
        }
      />
      {members.isPending && <Spinner />}
      {members.error && <ErrorNotice error={members.error} onRetry={members.refetch} />}
      {members.data && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Person</th>
                <th scope="col">Role</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {members.data.map((m) => (
                <MemberRow key={m.id} m={m} isMe={m.email === email} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <section aria-labelledby="roles-title">
        <h2 id="roles-title" className="section-title">
          Roles
        </h2>
        <dl className="facts">
          {ROLES.map((r) => (
            <div key={r.value} className="fact-row">
              <dt>{r.label}</dt>
              <dd>{r.does}</dd>
            </div>
          ))}
        </dl>
      </section>
      <Dialog open={inviting} onClose={() => setInviting(false)} title="Invite someone">
        <InviteForm onDone={() => setInviting(false)} />
      </Dialog>
    </>
  )
}
