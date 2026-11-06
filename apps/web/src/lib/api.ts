import type {
  Incident,
  InvestigateResponse,
  MemoryRecord,
  RemediationProposal,
  StreamEvent,
  TokenResponse,
  User,
} from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8010'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(
  path: string,
  options: { method?: string; token?: string; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (options.token) headers.Authorization = `Bearer ${options.token}`

  const response = await fetch(`${BASE_URL}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })

  if (response.status === 204) {
    return undefined as T
  }

  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message =
      typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`
    throw new ApiError(response.status, message)
  }
  return payload as T
}

// --- Auth ---

export function login(email: string, password: string): Promise<TokenResponse> {
  return request('/api/v1/auth/login', { method: 'POST', body: { email, password } })
}

export function registerTenant(payload: {
  tenant_name: string
  tenant_slug: string
  admin_email: string
  admin_password: string
  admin_full_name: string
}): Promise<User> {
  return request('/api/v1/auth/register-tenant', { method: 'POST', body: payload })
}

export function getMe(token: string): Promise<User> {
  return request('/api/v1/auth/me', { token })
}

// --- Incidents ---

export function listIncidents(token: string): Promise<Incident[]> {
  return request('/api/v1/incidents', { token })
}

export function getIncident(token: string, incidentId: string): Promise<Incident> {
  return request(`/api/v1/incidents/${incidentId}`, { token })
}

export function createIncident(
  token: string,
  payload: { title: string; service: string; environment: string; severity: string },
): Promise<Incident> {
  return request('/api/v1/incidents', { method: 'POST', token, body: payload })
}

export function investigate(token: string, incidentId: string): Promise<InvestigateResponse> {
  return request(`/api/v1/incidents/${incidentId}/investigate`, { method: 'POST', token })
}

/**
 * EventSource can't send an Authorization header, so the streaming
 * endpoint is consumed via fetch + a manual ReadableStream reader instead
 * — same reason the backend route is a POST, not a GET.
 */
export async function investigateStream(
  token: string,
  incidentId: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE_URL}/api/v1/incidents/${incidentId}/investigate/stream`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}))
    throw new ApiError(
      response.status,
      typeof payload.detail === 'string' ? payload.detail : 'Investigation stream failed to start',
    )
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')

      const lines = block.split('\n')
      const eventLine = lines.find((l) => l.startsWith('event: '))
      const dataLine = lines.find((l) => l.startsWith('data: '))
      if (!eventLine || !dataLine) continue

      const event = eventLine.replace('event: ', '').trim()
      const data = JSON.parse(dataLine.replace('data: ', ''))
      onEvent({ event, data } as StreamEvent)
    }
  }
}

// --- Remediations ---

export function listRemediationsForIncident(
  token: string,
  incidentId: string,
): Promise<RemediationProposal[]> {
  return request(`/api/v1/remediations/incident/${incidentId}`, { token })
}

export function approveRemediation(
  token: string,
  proposalId: string,
  actionParams?: Record<string, unknown>,
): Promise<RemediationProposal> {
  return request(`/api/v1/remediations/${proposalId}/approve`, {
    method: 'POST',
    token,
    body: actionParams ? { action_params: actionParams } : {},
  })
}

export function rejectRemediation(token: string, proposalId: string): Promise<RemediationProposal> {
  return request(`/api/v1/remediations/${proposalId}/reject`, { method: 'POST', token })
}

// --- Memories ---

export function listMemories(token: string): Promise<MemoryRecord[]> {
  return request('/api/v1/memories', { token })
}

export function deleteMemory(token: string, memoryId: string): Promise<void> {
  return request(`/api/v1/memories/${memoryId}`, { method: 'DELETE', token })
}

export function correctMemory(
  token: string,
  memoryId: string,
  content: string,
): Promise<MemoryRecord> {
  return request(`/api/v1/memories/${memoryId}`, { method: 'PATCH', token, body: { content } })
}

export function setProfilePreference(token: string, content: string): Promise<MemoryRecord> {
  return request('/api/v1/memories/profile', { method: 'PUT', token, body: { content } })
}
