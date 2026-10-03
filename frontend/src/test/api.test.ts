import { api, ApiError, clearKey, storeKey } from '../lib/api'

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => {
  vi.unstubAllGlobals()
  clearKey()
})

describe('api client', () => {
  it('sends the stored API key and query parameters', async () => {
    storeKey('secret', false)
    const fetchFn = mockFetch(200, { items: [], total: 0, limit: 20, offset: 0, backend: 'basic' })
    await api.articles({ q: 'floods', language: 'en', include_duplicates: undefined })
    const [url, init] = fetchFn.mock.calls[0]
    expect(url).toBe('/api/v1/articles?q=floods&language=en')
    expect(init.headers['X-API-Key']).toBe('secret')
  })

  it('maps FastAPI validation errors to fields', async () => {
    mockFetch(422, { detail: [{ loc: ['body', 'base_url'], msg: 'Value error, non-public ip address' }] })
    const err = await api.createSource({ name: 'x' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.fieldErrors).toEqual({ base_url: 'non-public ip address' })
  })

  it('reports network failures in plain language', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = await api.stats().catch((e) => e)
    expect(err.status).toBe(0)
    expect(err.message).toMatch(/Could not reach the Newsforge API/)
  })

  it('keeps the key in session storage unless asked to remember', () => {
    storeKey('k1', false)
    expect(sessionStorage.getItem('newsforge.apiKey')).toBe('k1')
    expect(localStorage.getItem('newsforge.apiKey')).toBeNull()
    storeKey('k2', true)
    expect(localStorage.getItem('newsforge.apiKey')).toBe('k2')
    expect(sessionStorage.getItem('newsforge.apiKey')).toBeNull()
  })
})
