import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import * as api from '../lib/api'
import { Badge } from '../components/Badge'
import { useAuth } from '../lib/auth'
import type { Incident, IncidentSeverity } from '../lib/types'

const SEVERITIES: IncidentSeverity[] = ['sev1', 'sev2', 'sev3', 'sev4']

export function IncidentsPage() {
  const { accessToken } = useAuth()
  const navigate = useNavigate()
  const [incidents, setIncidents] = useState<Incident[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  const [title, setTitle] = useState('')
  const [service, setService] = useState('checkout-service')
  const [environment, setEnvironment] = useState('production')
  const [severity, setSeverity] = useState<IncidentSeverity>('sev2')
  const [creating, setCreating] = useState(false)

  const load = () => {
    if (!accessToken) return
    api
      .listIncidents(accessToken)
      .then(setIncidents)
      .catch(() => setError('Could not load incidents.'))
  }

  useEffect(load, [accessToken])

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault()
    if (!accessToken) return
    setCreating(true)
    try {
      const incident = await api.createIncident(accessToken, { title, service, environment, severity })
      setShowForm(false)
      setTitle('')
      navigate(`/incidents/${incident.id}`)
    } catch {
      setError('Could not create incident.')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Incidents</h1>
          <p className="text-sm text-slate-500">Open an incident to run an AI-assisted investigation.</p>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500"
        >
          {showForm ? 'Cancel' : 'New incident'}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleCreate}
          className="mb-6 grid grid-cols-1 gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-5 sm:grid-cols-2"
        >
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-slate-300">Title</label>
            <input
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Checkout error rate elevated"
              className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300">Service</label>
            <input
              required
              value={service}
              onChange={(e) => setService(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300">Environment</label>
            <input
              required
              value={environment}
              onChange={(e) => setEnvironment(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300">Severity</label>
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value as IncidentSeverity)}
              className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s.toUpperCase()}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={creating}
              className="rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
            >
              {creating ? 'Creating…' : 'Create incident'}
            </button>
          </div>
        </form>
      )}

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <div className="overflow-hidden rounded-xl border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-900/60 text-slate-400">
            <tr>
              <th className="px-4 py-3 font-medium">Title</th>
              <th className="px-4 py-3 font-medium">Service</th>
              <th className="px-4 py-3 font-medium">Severity</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {incidents === null && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            )}
            {incidents !== null && incidents.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  No incidents yet.
                </td>
              </tr>
            )}
            {incidents?.map((incident) => (
              <tr
                key={incident.id}
                onClick={() => navigate(`/incidents/${incident.id}`)}
                className="cursor-pointer text-slate-200 hover:bg-slate-900/60"
              >
                <td className="px-4 py-3">{incident.title}</td>
                <td className="px-4 py-3 text-slate-400">{incident.service}</td>
                <td className="px-4 py-3">
                  <Badge value={incident.severity} />
                </td>
                <td className="px-4 py-3">
                  <Badge value={incident.status} />
                </td>
                <td className="px-4 py-3 text-slate-500">
                  {new Date(incident.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
