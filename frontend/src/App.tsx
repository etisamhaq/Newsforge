import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { useAuth } from './lib/auth'
import { Layout } from './components/Layout'
import { Spinner } from './components/ui'
import { Login } from './pages/Login'
import { Dashboard } from './pages/Dashboard'
import { NotFound } from './pages/NotFound'

// Secondary screens load on demand to keep the first paint small.
const Sources = lazy(() => import('./pages/Sources').then((m) => ({ default: m.Sources })))
const SourceDetail = lazy(() => import('./pages/SourceDetail').then((m) => ({ default: m.SourceDetail })))
const Crawls = lazy(() => import('./pages/Crawls').then((m) => ({ default: m.Crawls })))
const CrawlDetail = lazy(() => import('./pages/CrawlDetail').then((m) => ({ default: m.CrawlDetail })))
const Articles = lazy(() => import('./pages/Articles').then((m) => ({ default: m.Articles })))
const ArticleDetail = lazy(() => import('./pages/ArticleDetail').then((m) => ({ default: m.ArticleDetail })))
const Debugger = lazy(() => import('./pages/Debugger').then((m) => ({ default: m.Debugger })))

export function App() {
  const { apiKey } = useAuth()
  if (!apiKey) return <Login />
  return (
    <BrowserRouter>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="sources" element={<Sources />} />
            <Route path="sources/:id" element={<SourceDetail />} />
            <Route path="crawls" element={<Crawls />} />
            <Route path="crawls/:id" element={<CrawlDetail />} />
            <Route path="articles" element={<Articles />} />
            <Route path="articles/:id" element={<ArticleDetail />} />
            <Route path="debug" element={<Debugger />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
