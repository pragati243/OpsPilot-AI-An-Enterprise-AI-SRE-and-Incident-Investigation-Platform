from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.incident import IncidentSeverity, IncidentStatus
from app.models.user import User, UserRole
from app.repositories.incident_repository import IncidentRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository
from app.tools.context import ToolContext
from app.tools.remediation import propose_remediation
from app.tools.schemas import ProposeRemediationInput

REGISTER_PAYLOAD = {
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme-api-remediations",
    "admin_email": "admin@acme-remediations.io",
    "admin_password": "correct-horse-battery",
    "admin_full_name": "Ada Admin",
}


async def _register_and_login(client: AsyncClient, **overrides: str) -> str:
    payload = {**REGISTER_PAYLOAD, **overrides}
    await client.post("/api/v1/auth/register-tenant", json=payload)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["admin_email"], "password": payload["admin_password"]},
    )
    return str(login.json()["access_token"])


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_incident_and_proposal(
    client: AsyncClient, db_session: AsyncSession, token: str
) -> tuple[str, str]:
    """There's no API endpoint that creates a remediation proposal directly
    (only the agent's report node does, via the propose_remediation tool),
    so these tests set one up by calling the real tool function against
    the same `db_session` the `client` fixture's overridden get_db uses —
    same pattern as `tool_ctx`, just with a specific pre-existing user.
    """
    me = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    user_id = me.json()["id"]
    tenant_id = me.json()["tenant_id"]

    user = await UserRepository(db_session).get_by_id(user_id)
    incident = await IncidentRepository(db_session).create(
        tenant_id=tenant_id,
        title="Checkout error rate elevated",
        service="checkout-service",
        environment="production",
        severity=IncidentSeverity.SEV2,
        status=IncidentStatus.INVESTIGATING,
        created_by=user_id,
    )
    ctx = ToolContext(tenant_id=tenant_id, user=user, db=db_session)
    proposal = await propose_remediation(
        ctx,
        ProposeRemediationInput(
            incident_id=incident.id,
            action_type="restart_service",
            action_params={"service": "checkout-service"},
            rationale="Clear stuck DB connections.",
        ),
    )
    return str(incident.id), str(proposal.proposal_id)


async def test_list_remediations_for_incident(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-rem-list", admin_email="admin@acme-rem-list.io"
    )
    incident_id, proposal_id = await _create_incident_and_proposal(client, db_session, token)

    resp = await client.get(
        f"/api/v1/remediations/incident/{incident_id}", headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    proposals = resp.json()
    assert len(proposals) == 1
    assert proposals[0]["id"] == proposal_id
    assert proposals[0]["status"] == "pending_approval"


async def test_admin_can_approve_a_pending_proposal(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-rem-approve", admin_email="admin@acme-rem-approve.io"
    )
    _, proposal_id = await _create_incident_and_proposal(client, db_session, token)

    resp = await client.post(
        f"/api/v1/remediations/{proposal_id}/approve", json={}, headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["decided_at"] is not None


async def test_approving_with_edited_params_marks_it_edited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-rem-edit", admin_email="admin@acme-rem-edit.io"
    )
    _, proposal_id = await _create_incident_and_proposal(client, db_session, token)

    resp = await client.post(
        f"/api/v1/remediations/{proposal_id}/approve",
        json={"action_params": {"service": "checkout-service", "graceful": True}},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "edited"
    assert body["action_params"]["graceful"] is True


async def test_admin_can_reject_a_pending_proposal(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-rem-reject", admin_email="admin@acme-rem-reject.io"
    )
    _, proposal_id = await _create_incident_and_proposal(client, db_session, token)

    resp = await client.post(
        f"/api/v1/remediations/{proposal_id}/reject", headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


async def test_cannot_decide_an_already_decided_proposal(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-rem-twice", admin_email="admin@acme-rem-twice.io"
    )
    _, proposal_id = await _create_incident_and_proposal(client, db_session, token)

    first = await client.post(
        f"/api/v1/remediations/{proposal_id}/reject", headers=_auth_headers(token)
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/remediations/{proposal_id}/approve", json={}, headers=_auth_headers(token)
    )
    assert second.status_code == 409


async def test_viewer_cannot_approve_a_proposal(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Only admin/approver roles can decide — enforced via require_role,
    exercised here for the first time against a real route.
    """
    token = await _register_and_login(
        client, tenant_slug="acme-rem-viewer", admin_email="admin@acme-rem-viewer.io"
    )
    _, proposal_id = await _create_incident_and_proposal(client, db_session, token)

    tenant = await TenantRepository(db_session).get_by_slug("acme-rem-viewer")
    assert tenant is not None
    viewer = User(
        tenant_id=tenant.id,
        email="viewer@acme-rem-viewer.io",
        hashed_password=hash_password("correct-horse-battery"),
        full_name="Vera Viewer",
        role=UserRole.VIEWER,
    )
    db_session.add(viewer)
    await db_session.flush()

    viewer_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@acme-rem-viewer.io", "password": "correct-horse-battery"},
    )
    viewer_token = viewer_login.json()["access_token"]

    resp = await client.post(
        f"/api/v1/remediations/{proposal_id}/approve",
        json={},
        headers=_auth_headers(viewer_token),
    )
    assert resp.status_code == 403
