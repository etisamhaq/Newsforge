import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from '../lib/auth'
import { storeKey, clearKey } from '../lib/api'

function Probe() {
  const { status, workspace, can } = useAuth()
  return (
    <p>
      {status}|{workspace?.role ?? '-'}|{String(can('viewer'))}{String(can('editor'))}{String(can('admin'))}
    </p>
  )
}

function renderWith(fetchImpl: (url: string) => Response) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => fetchImpl(url)))
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => {
  vi.unstubAllGlobals()
  clearKey()
})

describe('auth state (API-key mode)', () => {
  it('is signed out without a key', async () => {
    renderWith(() => json({}))
    expect(await screen.findByText(/^signedOut\|/)).toBeInTheDocument()
  })

  it('derives permissions from the role', async () => {
    storeKey('k', false)
    renderWith(() => json({ email: null, via: 'api_key', workspaces: [{ id: 7, name: 'News', role: 'editor', owned: false }] }))
    expect(await screen.findByText('ready|editor|truetruefalse')).toBeInTheDocument()
  })

  it('asks to create a workspace when the person has none', async () => {
    storeKey('k', false)
    renderWith(() => json({ email: 'a@b.com', via: 'user', workspaces: [] }))
    expect(await screen.findByText(/^noWorkspace\|/)).toBeInTheDocument()
  })

  it('sends the chosen workspace with every request', async () => {
    storeKey('k', false)
    const { setWorkspaceId, api } = await import('../lib/api')
    setWorkspaceId(42)
    const fetchFn = vi.fn(async () => json({ items: [], total: 0, limit: 1, offset: 0 }))
    vi.stubGlobal('fetch', fetchFn)
    await api.sources()
    const init = (fetchFn.mock.calls[0] as unknown as [string, RequestInit])[1]
    expect((init.headers as Record<string, string>)['X-Workspace-Id']).toBe('42')
    setWorkspaceId(null)
  })
})
