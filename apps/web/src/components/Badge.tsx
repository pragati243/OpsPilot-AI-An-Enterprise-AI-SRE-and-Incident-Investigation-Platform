const PALETTE: Record<string, string> = {
  // Incident status / severity / memory status / remediation status —
  // one shared palette, keyed by the raw backend string values, so a new
  // status just needs one line here rather than a new component.
  open: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  investigating: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  resolved: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  closed: 'bg-slate-600/15 text-slate-400 ring-slate-600/30',
  sev1: 'bg-red-500/15 text-red-300 ring-red-500/30',
  sev2: 'bg-orange-500/15 text-orange-300 ring-orange-500/30',
  sev3: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  sev4: 'bg-slate-600/15 text-slate-400 ring-slate-600/30',
  active: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  superseded: 'bg-slate-600/15 text-slate-400 ring-slate-600/30',
  deleted: 'bg-slate-600/15 text-slate-400 ring-slate-600/30',
  pending_approval: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  approved: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  rejected: 'bg-red-500/15 text-red-300 ring-red-500/30',
  edited: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  low: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  medium: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  high: 'bg-red-500/15 text-red-300 ring-red-500/30',
  unresolved: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  escalated: 'bg-red-500/15 text-red-300 ring-red-500/30',
}

export function Badge({ value }: { value: string }) {
  const classes = PALETTE[value] ?? 'bg-slate-600/15 text-slate-400 ring-slate-600/30'
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${classes}`}>
      {value.replace(/_/g, ' ')}
    </span>
  )
}
