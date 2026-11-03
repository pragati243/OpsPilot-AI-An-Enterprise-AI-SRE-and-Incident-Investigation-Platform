from httpx import AsyncClient

from app.agents.schemas import Assessment, InvestigationPlan, InvestigationReport
from app.api.deps import get_agent_llm
from app.main import app
from tests.fakes import FakeAgentLLM

REGISTER_PAYLOAD = {
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme-api-incidents",
    "admin_email": "admin@acme-incidents.io",
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


def _trivial_fake_llm(outcome: str = "unresolved") -> FakeAgentLLM:
    return FakeAgentLLM(
        tool_call_script=[[]],
        structured_responses={
            InvestigationPlan: [InvestigationPlan(hypothesis="n/a", steps=[])],
            Assessment: [
                Assessment(leading_hypothesis="n/a", confidence=0.5, ready_to_report=True)
            ],
            InvestigationReport: [
                InvestigationReport(
                    diagnosis="Not enough history for this fresh incident.",
                    evidence_summary="n/a",
                    resolution=None,
                    citations=[],
                    confidence=0.5,
                    outcome=outcome,
                    recommended_actions=[],
                    uncertainty_note="n/a" if outcome == "unresolved" else None,
                )
            ],
        },
    )


async def test_create_list_get_incident(client: AsyncClient) -> None:
    token = await _register_and_login(client)

    create_resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Checkout down", "service": "checkout-service", "severity": "sev2"},
        headers=_auth_headers(token),
    )
    assert create_resp.status_code == 201
    incident_id = create_resp.json()["id"]

    list_resp = await client.get("/api/v1/incidents", headers=_auth_headers(token))
    assert list_resp.status_code == 200
    assert any(i["id"] == incident_id for i in list_resp.json())

    get_resp = await client.get(f"/api/v1/incidents/{incident_id}", headers=_auth_headers(token))
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Checkout down"


async def test_create_incident_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/incidents", json={"title": "x", "service": "y", "severity": "sev3"}
    )
    assert resp.status_code == 401


async def test_investigate_endpoint_uses_overridden_fake_llm(client: AsyncClient) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-investigate", admin_email="admin@acme-investigate.io"
    )
    create_resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Checkout down", "service": "checkout-service", "severity": "sev2"},
        headers=_auth_headers(token),
    )
    incident_id = create_resp.json()["id"]

    app.dependency_overrides[get_agent_llm] = lambda: _trivial_fake_llm("unresolved")

    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate", headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_id"] == incident_id
    assert body["report"]["outcome"] == "unresolved"


async def test_investigate_unknown_incident_returns_404(client: AsyncClient) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-404", admin_email="admin@acme-404.io"
    )
    app.dependency_overrides[get_agent_llm] = lambda: FakeAgentLLM()

    resp = await client.post(
        "/api/v1/incidents/00000000-0000-0000-0000-000000000000/investigate",
        headers=_auth_headers(token),
    )
    assert resp.status_code == 404


async def test_incidents_are_tenant_isolated(client: AsyncClient) -> None:
    token_a = await _register_and_login(
        client, tenant_slug="acme-tenant-a", admin_email="admin@tenant-a.io"
    )
    create_resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Tenant A incident", "service": "checkout-service", "severity": "sev3"},
        headers=_auth_headers(token_a),
    )
    incident_id = create_resp.json()["id"]

    token_b = await _register_and_login(
        client, tenant_slug="acme-tenant-b", admin_email="admin@tenant-b.io"
    )
    get_resp = await client.get(f"/api/v1/incidents/{incident_id}", headers=_auth_headers(token_b))
    assert get_resp.status_code == 404

    list_resp = await client.get("/api/v1/incidents", headers=_auth_headers(token_b))
    assert all(i["id"] != incident_id for i in list_resp.json())
