import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Badge } from '../components/Badge'
import * as api from '../lib/api'
import { useAuth } from '../lib/auth'
import type { Incident, InvestigationReport, RemediationProposal } from '../lib/types'

const STAGES = [
  { key: 'intake', label: 'Intake' },
  { key: 'plan', label: 'Plan' },
  { key: 'gather', label: 'Gather evidence' },
  { key: 'assess', label: 'Assess' },
  { key: 'report', label: 'Report' },
] as const

function stageForNode(node: string): string {
  if (node === 'agent' || node === 'execute_tools') return 'gather'
  return node
}

export function IncidentDetailPage() {
  const { incidentId } = useParams<{ incidentId: string }>()
  const { accessToken, user } = useAuth()

  const [incident, setIncident] = useState<Incident | null>(null)
  const [report, setReport] = useState<InvestigationReport | null>(null)
  const [remediations, setRemediations] = useState<RemediationProposal[]>([])
  const [streaming, setStreaming] = useState(false)
  const [nodeLog, setNodeLog] = useState<string[]>([])
  const [streamError, setStreamError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const canApprove = user?.role === 'admin' || user?.role === 'approver'

  const loadRemediations = () => {
    if (!accessToken || !incidentId) return
    api.listRemediationsForIncident(accessToken, incidentId).then(setRemediations).catch(() => {})
  }

  useEffect(() => {
    if (!accessToken || !incidentId) return
    api.getIncident(accessToken, incidentId).then(setIncident).catch(() => {})
    loadRemediations()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, incidentId])

  const handleInvestigate = () => {
    if (!accessToken || !incidentId) return
    setStreaming(true)
    setStreamError(null)
    setReport(null)
    setNodeLog([])

    const controller = new AbortController()
    abortRef.current = controller

    api
      .investigateStream(
        accessToken,
        incidentId,
        (event) => {
          if (event.event === 'node_complete') {
            setNodeLog((log) => [...log, event.data.node])
          } else if (event.event === 'report') {
            setReport(event.data)
            setStreaming(false)
            loadRemediations()
          } else if (event.event === 'error') {
            setStreamError(event.data.message)
            setStreaming(false)
          }
        },
        controller.signal,
      )
      .catch((err) => {
        setStreamError(err instanceof Error ? err.message : 'Investigation failed to start.')
        setStreaming(false)
      })
  }

  const handleDecision = async (proposalId: string, decision: 'approve' | 'reject') => {
    if (!accessToken) return
    try {
      if (decision === 'approve') await api.approveRemediation(accessToken, proposalId)
      else await api.rejectRemediation(accessToken, proposalId)
      loadRemediations()
    } catch {
      // Surfacing this inline keeps the page simple; a toast system would
      // be the next thing to add if this dashboard grows beyond a demo.
    }
  }

  const currentStage = nodeLog.length > 0 ? stageForNode(nodeLog[nodeLog.length - 1]) : null
  const completedStages = new Set(nodeLog.map(stageForNode))

  if (!incident) return <p className="text-slate-500">Loading…</p>

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-100">{incident.title}</h1>
          <Badge value={incident.severity} />
          <Badge value={incident.status} />
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {incident.service} · {incident.environment} · opened{' '}
          {new Date(incident.created_at).toLocaleString()}
        </p>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">Investigation</h2>
          <button
            onClick={handleInvestigate}
            disabled={streaming}
            className="rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
          >
            {streaming ? 'Investigating…' : report ? 'Re-investigate' : 'Investigate'}
          </button>
        </div>

        {(streaming || nodeLog.length > 0) && (
          <ol className="mt-4 flex flex-wrap gap-2">
            {STAGES.map((stage) => {
              const done = completedStages.has(stage.key) && stage.key !== currentStage
              const active = currentStage === stage.key
              return (
                <li
                  key={stage.key}
                  className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${
                    active
                      ? 'bg-sky-500/15 text-sky-300 ring-sky-500/30'
                      : done
                        ? 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30'
                        : 'bg-slate-800 text-slate-500 ring-slate-700'
                  }`}
                >
                  {active && !report ? '● ' : done ? '✓ ' : ''}
                  {stage.label}
                </li>
              )
            })}
          </ol>
        )}

        {streamError && <p className="mt-4 text-sm text-red-400">{streamError}</p>}

        {report && (
          <div className="mt-5 space-y-4 border-t border-slate-800 pt-5">
            <div className="flex items-center gap-3">
              <Badge value={report.outcome} />
              <span className="text-sm text-slate-400">
                confidence {(report.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-300">Diagnosis</h3>
              <p className="mt-1 text-sm text-slate-200">{report.diagnosis}</p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-300">Evidence summary</h3>
              <p className="mt-1 text-sm text-slate-400">{report.evidence_summary}</p>
            </div>
            {report.uncertainty_note && (
              <div className="rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
                {report.uncertainty_note}
              </div>
            )}
            {report.citations.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-slate-300">Citations</h3>
                <div className="mt-1 flex flex-wrap gap-2">
                  {report.citations.map((citation) => (
                    <code
                      key={citation}
                      className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300"
                    >
                      {citation}
                    </code>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-semibold text-slate-200">Proposed remediations</h2>
        <p className="mt-1 text-xs text-slate-500">
          Never executed automatically — every proposal needs an explicit human decision.
        </p>
        {remediations.length === 0 && (
          <p className="mt-3 text-sm text-slate-500">None proposed yet.</p>
        )}
        <ul className="mt-3 space-y-3">
          {remediations.map((proposal) => (
            <li
              key={proposal.id}
              className="rounded-lg border border-slate-800 bg-slate-950/60 p-4"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <code className="text-sm text-slate-200">{proposal.action_type}</code>
                  <Badge value={proposal.risk_level} />
                  <Badge value={proposal.status} />
                </div>
                {proposal.status === 'pending_approval' && canApprove && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleDecision(proposal.id, 'approve')}
                      className="rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-500"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => handleDecision(proposal.id, 'reject')}
                      className="rounded-md bg-red-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-500"
                    >
                      Reject
                    </button>
                  </div>
                )}
                {proposal.status === 'pending_approval' && !canApprove && (
                  <span className="text-xs text-slate-500">Needs admin/approver</span>
                )}
              </div>
              <p className="mt-2 text-sm text-slate-400">{proposal.rationale}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
