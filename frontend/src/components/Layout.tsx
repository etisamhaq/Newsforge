import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useTheme } from '../lib/theme'
import {
  IconArticles,
  IconCrawls,
  IconDashboard,
  IconDebug,
  IconMenu,
  IconMoon,
  IconSignOut,
  IconSources,
  IconSun,
} from './icons'

const NAV = [
  { to: '/', label: 'Dashboard', icon: IconDashboard, end: true },
  { to: '/sources', label: 'Sources', icon: IconSources },
  { to: '/crawls', label: 'Crawls', icon: IconCrawls },
  { to: '/articles', label: 'Articles', icon: IconArticles },
  { to: '/debug', label: 'Extraction debugger', icon: IconDebug },
]

function ServiceStatus() {
  const { data } = useQuery({ queryKey: ['readiness'], queryFn: api.readiness, refetchInterval: 30_000 })
  if (!data) return null
  const ok = data.status === 'ok'
  const failing = Object.entries(data.checks)
    .filter(([, v]) => v !== 'ok')
    .map(([k]) => k)
  return (
    <p className={`service-status ${ok ? 'is-ok' : 'is-degraded'}`}>
      <span className="dot" aria-hidden="true" />
      {ok ? 'All services up' : `Unavailable: ${failing.join(', ')}`}
    </p>
  )
}

export function Layout() {
  const { signOut } = useAuth()
  const { theme, toggle } = useTheme()
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className={`rail ${menuOpen ? 'is-open' : ''}`}>
        <div className="rail-top">
          <NavLink to="/" className="wordmark" aria-label="Newsforge home">
            <span className="wordmark-mark" aria-hidden="true">
              N
            </span>
            Newsforge
          </NavLink>
          <button
            type="button"
            className="icon-btn menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="primary-nav"
            onClick={() => setMenuOpen((o) => !o)}
          >
            <IconMenu />
            <span className="sr-only">Menu</span>
          </button>
        </div>
        <nav id="primary-nav" aria-label="Primary" className="nav">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className="nav-link" onClick={() => setMenuOpen(false)}>
              <Icon />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="rail-footer">
          <ServiceStatus />
          <div className="rail-actions">
            <button type="button" className="icon-btn" onClick={toggle} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
              {theme === 'dark' ? <IconSun /> : <IconMoon />}
            </button>
            <button type="button" className="btn btn-quiet btn-small" onClick={signOut}>
              <IconSignOut size={16} />
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main id="main" className="main" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  )
}
