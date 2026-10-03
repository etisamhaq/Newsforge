import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@fontsource-variable/instrument-sans'
import '@fontsource-variable/newsreader/opsz.css'
import './styles/app.css'
import { ApiError } from './lib/api'
import { AuthProvider } from './lib/auth'
import { initialTheme } from './lib/theme'
import { ToastProvider } from './components/toast'
import { App } from './App'

document.documentElement.dataset.theme = initialTheme()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      // Don't retry client errors (bad key, not found, validation).
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
)
