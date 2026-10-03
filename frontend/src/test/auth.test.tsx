import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from '../lib/auth'
import { storeKey, clearKey } from '../lib/api'

function Probe() {
  const { status, me, can } = useAuth()
  return (
    <p>
      {status}|{me?.role ?? '-'}|{String(can('viewer'))}{String(can('editor'))}{String(can('admin'))}
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
    renderWith(() => json({ email: null, role: 'editor', via: 'api_key' }))
    expect(await screen.findByText('ready|editor|truetruefalse')).toBeInTheDocument()
  })

  it('shows the no-access state on 403', async () => {
    storeKey('k', false)
    renderWith(() => json({ detail: 'not on the team' }, 403))
    expect(await screen.findByText(/^noAccess\|/)).toBeInTheDocument()
  })
})
