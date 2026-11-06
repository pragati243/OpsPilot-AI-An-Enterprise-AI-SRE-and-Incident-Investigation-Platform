// Mirrors apps/api/app/schemas/* and apps/api/app/models/* StrEnum values
// exactly. Kept hand-written rather than generated — the API surface is
// small and stable enough that a codegen step would be more ceremony than
// value right now.

export type UserRole = 'admin' | 'sre' | 'approver' | 'viewer'

export interface User {
  id: string
  tenant_id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export type IncidentSeverity = 'sev1' | 'sev2' | 'sev3' | 'sev4'
export type IncidentStatus = 'open' | 'investigating' | 'resolved' | 'closed'

export interface Incident {
  id: string
  title: string
  service: string
  environment: string
  severity: IncidentSeverity
  status: IncidentStatus
  created_at: string
  resolved_at: string | null
}

export interface RecommendedAction {
  action_type: string
  rationale: string
}

export type InvestigationOutcome = 'resolved' | 'unresolved' | 'escalated'

export interface InvestigationReport {
  diagnosis: string
  evidence_summary: string
  resolution: string | null
  citations: string[]
  confidence: number
  outcome: InvestigationOutcome
  recommended_actions: RecommendedAction[]
  uncertainty_note: string | null
}

export interface InvestigateResponse {
  incident_id: string
  report: InvestigationReport
}

export type StreamEventName = 'node_complete' | 'report' | 'error'

export type StreamEvent =
  | { event: 'node_complete'; data: { node: string } }
  | { event: 'report'; data: InvestigationReport }
  | { event: 'error'; data: { message: string } }

export type MemoryType = 'semantic' | 'procedural' | 'profile'
export type MemoryProvenance = 'user_confirmed' | 'system_extracted' | 'imported'
export type MemoryStatus = 'active' | 'superseded' | 'deleted'

export interface MemoryRecord {
  id: string
  memory_type: MemoryType
  content: string
  provenance: MemoryProvenance
  confidence: number
  status: MemoryStatus
  superseded_by: string | null
  source_episode_id: string | null
  last_verified_at: string | null
  created_at: string
}

export type RemediationRiskLevel = 'low' | 'medium' | 'high'
export type RemediationStatus = 'pending_approval' | 'approved' | 'rejected' | 'edited'

export interface RemediationProposal {
  id: string
  incident_id: string
  action_type: string
  action_params: Record<string, unknown>
  rationale: string
  risk_level: RemediationRiskLevel
  status: RemediationStatus
  proposed_by: string | null
  decided_by: string | null
  decided_at: string | null
  created_at: string
}
