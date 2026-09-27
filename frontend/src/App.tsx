import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api, type User } from './api'
import AccountPage from './pages/AccountPage'
import BackupsPage from './pages/BackupsPage'
import CollectionPage from './pages/CollectionPage'
import DashboardPage from './pages/DashboardPage'
import ImportPage from './pages/ImportPage'
import LoginPage from './pages/LoginPage'
import PlatformsPage from './pages/PlatformsPage'
import ScraperPage from './pages/ScraperPage'
import { SharedCollectionRoute, SharedListPage } from './pages/SharedPage'
import SetupPage from './pages/SetupPage'
import UsersPage from './pages/UsersPage'

export default function App() {
  const setup = useQuery({
    queryKey: ['setup'],
    queryFn: () => api.get<{ needs_setup: boolean; allow_registration: boolean }>('/setup/status'),
  })
  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<User>('/auth/me'),
    enabled: setup.data?.needs_setup === false,
  })

  if (setup.isLoading || me.isLoading) return <div className="center muted">Loading…</div>
  if (setup.isError) return <div className="center error">Cannot reach server.</div>
  if (setup.data?.needs_setup) return <SetupPage />
  if (!me.data) return <LoginPage allowRegistration={setup.data!.allow_registration} />
  return <Shell user={me.data} />
}

function Shell({ user }: { user: User }) {
  const qc = useQueryClient()
  const logout = useMutation({
    mutationFn: () => api.post('/auth/logout'),
    onSuccess: () => {
      qc.clear()
      window.location.assign('/')
    },
  })

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">🎮 VGVault</div>
        <nav>
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/collection">Collection</NavLink>
          <NavLink to="/shared" end={false}>
            Shared
          </NavLink>
          <NavLink to="/platforms">Platforms</NavLink>
          {user.role === 'admin' && (
            <>
              <NavLink to="/admin/prices">Price tracking</NavLink>
              <NavLink to="/admin/users">Users</NavLink>
              <NavLink to="/admin/backups">Backups</NavLink>
            </>
          )}
        </nav>
        <div className="spacer" />
        <NavLink to="/account" className="muted">
          {user.username}
          {user.role === 'admin' && <span className="badge">admin</span>}
        </NavLink>
        <button className="ghost" onClick={() => logout.mutate()}>
          Log out
        </button>
      </header>
      <main>
        <Routes>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/collection" element={<CollectionPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/shared" element={<SharedListPage />} />
          <Route path="/shared/:id" element={<SharedCollectionRoute />} />
          <Route path="/platforms" element={<PlatformsPage isAdmin={user.role === 'admin'} />} />
          <Route path="/account" element={<AccountPage user={user} />} />
          {user.role === 'admin' && <Route path="/admin/users" element={<UsersPage me={user} />} />}
          {user.role === 'admin' && <Route path="/admin/prices" element={<ScraperPage />} />}
          {user.role === 'admin' && <Route path="/admin/backups" element={<BackupsPage />} />}
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  )
}
