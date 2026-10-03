import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Meter, StatusBadge } from '../components/ui'
import { AuthProvider } from '../lib/auth'
import { Login } from '../pages/Login'

describe('components', () => {
  it('shows job status as text, not colour alone', () => {
    render(<StatusBadge status="failed" />)
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('exposes scores as an accessible meter', () => {
    render(<Meter value={0.87} label="Extraction confidence" />)
    const meter = screen.getByRole('meter', { name: 'Extraction confidence' })
    expect(meter).toHaveAttribute('aria-valuenow', '0.87')
    expect(screen.getByText('87%')).toBeInTheDocument()
  })
})

describe('sign in', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('explains a rejected key', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'invalid or missing API key' }), { status: 401 })))
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthProvider>
          <Login />
        </AuthProvider>
      </QueryClientProvider>,
    )
    await userEvent.type(screen.getByLabelText('API key'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That API key was not accepted')
  })
})
