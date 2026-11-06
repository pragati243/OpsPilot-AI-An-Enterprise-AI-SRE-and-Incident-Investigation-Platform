import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium transition-colors ${
    isActive ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
  }`

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-slate-950">
      <header className="border-b border-slate-800 bg-slate-900/60">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-6">
            <span className="text-sm font-semibold tracking-wide text-slate-100">
              OpsPilot <span className="text-sky-400">AI</span>
            </span>
            <nav className="flex gap-1">
              <NavLink to="/incidents" className={navLinkClass}>
                Incidents
              </NavLink>
              <NavLink to="/memories" className={navLinkClass}>
                Memory
              </NavLink>
            </nav>
          </div>
          <div className="flex items-center gap-4 text-sm text-slate-400">
            {user && (
              <span>
                {user.full_name} <span className="text-slate-600">·</span>{' '}
                <span className="uppercase text-slate-500">{user.role}</span>
              </span>
            )}
            <button
              onClick={() => {
                logout()
                navigate('/login')
              }}
              className="rounded-md border border-slate-700 px-3 py-1 text-slate-300 hover:bg-slate-800"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
