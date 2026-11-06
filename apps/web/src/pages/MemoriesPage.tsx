import { useEffect, useState, type FormEvent } from 'react'
import { Badge } from '../components/Badge'
import * as api from '../lib/api'
import { useAuth } from '../lib/auth'
import type { MemoryRecord, MemoryType } from '../lib/types'

const TYPE_LABEL: Record<MemoryType, string> = {
  semantic: 'Semantic (service facts)',
  procedural: 'Procedural (confirmed fixes)',
  profile: 'Profile (your preferences)',
}

export function MemoriesPage() {
  const { accessToken } = useAuth()
  const [memories, setMemories] = useState<MemoryRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [preference, setPreference] = useState('')
  const [savingPreference, setSavingPreference] = useState(false)

  const load = () => {
    if (!accessToken) return
    api
      .listMemories(accessToken)
      .then(setMemories)
      .catch(() => setError('Could not load memories.'))
  }

  useEffect(load, [accessToken])

  const handleDelete = async (id: string) => {
    if (!accessToken) return
    try {
      await api.deleteMemory(accessToken, id)
      load()
    } catch {
      setError('Could not delete that memory.')
    }
  }

  const startEdit = (memory: MemoryRecord) => {
    setEditingId(memory.id)
    setEditValue(memory.content)
  }

  const handleSaveEdit = async (event: FormEvent) => {
    event.preventDefault()
    if (!accessToken || !editingId) return
    try {
      await api.correctMemory(accessToken, editingId, editValue)
      setEditingId(null)
      load()
    } catch {
      setError('Could not save that correction.')
    }
  }

  const handleSetPreference = async (event: FormEvent) => {
    event.preventDefault()
    if (!accessToken || !preference.trim()) return
    setSavingPreference(true)
    try {
      await api.setProfilePreference(accessToken, preference.trim())
      setPreference('')
      load()
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : 'Could not save preference.')
    } finally {
      setSavingPreference(false)
    }
  }

  const grouped = memories
    ? {
        profile: memories.filter((m) => m.memory_type === 'profile'),
        shared: memories.filter((m) => m.memory_type !== 'profile'),
      }
    : null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Memory</h1>
        <p className="text-sm text-slate-500">
          Long-term knowledge reused across investigations — distinct from any one conversation.
        </p>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-semibold text-slate-200">Your reporting preference</h2>
        <p className="mt-1 text-xs text-slate-500">
          Recalled into every investigation's report step — e.g. "prefers concise reports with
          evidence first."
        </p>
        <form onSubmit={handleSetPreference} className="mt-3 flex gap-2">
          <input
            value={preference}
            onChange={(e) => setPreference(e.target.value)}
            placeholder="Prefers concise reports with evidence first."
            className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
          />
          <button
            type="submit"
            disabled={savingPreference}
            className="rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
          >
            Save
          </button>
        </form>
      </div>

      {grouped?.profile.map((memory) => (
        <MemoryRow
          key={memory.id}
          memory={memory}
          editing={editingId === memory.id}
          editValue={editValue}
          onEditValueChange={setEditValue}
          onStartEdit={() => startEdit(memory)}
          onCancelEdit={() => setEditingId(null)}
          onSaveEdit={handleSaveEdit}
          onDelete={() => handleDelete(memory.id)}
        />
      ))}

      <div>
        <h2 className="mb-3 text-sm font-semibold text-slate-200">
          Shared knowledge (semantic &amp; procedural)
        </h2>
        <div className="space-y-3">
          {grouped === null && <p className="text-sm text-slate-500">Loading…</p>}
          {grouped?.shared.length === 0 && (
            <p className="text-sm text-slate-500">
              Nothing learned yet — facts get extracted here automatically after an investigation
              is resolved.
            </p>
          )}
          {grouped?.shared.map((memory) => (
            <MemoryRow
              key={memory.id}
              memory={memory}
              editing={editingId === memory.id}
              editValue={editValue}
              onEditValueChange={setEditValue}
              onStartEdit={() => startEdit(memory)}
              onCancelEdit={() => setEditingId(null)}
              onSaveEdit={handleSaveEdit}
              onDelete={() => handleDelete(memory.id)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function MemoryRow({
  memory,
  editing,
  editValue,
  onEditValueChange,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onDelete,
}: {
  memory: MemoryRecord
  editing: boolean
  editValue: string
  onEditValueChange: (value: string) => void
  onStartEdit: () => void
  onCancelEdit: () => void
  onSaveEdit: (event: FormEvent) => void
  onDelete: () => void
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Badge value={memory.memory_type} />
          <span className="text-xs text-slate-500">{TYPE_LABEL[memory.memory_type]}</span>
          <span className="text-xs text-slate-600">
            confidence {(memory.confidence * 100).toFixed(0)}%
          </span>
        </div>
        {!editing && (
          <div className="flex gap-2">
            <button onClick={onStartEdit} className="text-xs text-sky-400 hover:underline">
              Correct
            </button>
            <button onClick={onDelete} className="text-xs text-red-400 hover:underline">
              Delete
            </button>
          </div>
        )}
      </div>
      {editing ? (
        <form onSubmit={onSaveEdit} className="mt-2 flex gap-2">
          <input
            value={editValue}
            onChange={(e) => onEditValueChange(e.target.value)}
            className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
          />
          <button
            type="submit"
            className="rounded-md bg-sky-600 px-3 py-2 text-xs font-medium text-white hover:bg-sky-500"
          >
            Save
          </button>
          <button
            type="button"
            onClick={onCancelEdit}
            className="rounded-md border border-slate-700 px-3 py-2 text-xs text-slate-300"
          >
            Cancel
          </button>
        </form>
      ) : (
        <p className="mt-2 text-sm text-slate-200">{memory.content}</p>
      )}
    </div>
  )
}
