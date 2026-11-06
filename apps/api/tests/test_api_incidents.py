import json

import structlog.testing
from httpx import AsyncClient

from app.agents.schemas import Assessment, InvestigationPlan, InvestigationReport
from app.api.deps import get_agent_llm
from app.core.redis_client import get_redis_client
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


async def test_investigate_stream_emits_node_events_then_report(client: AsyncClient) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-stream", admin_email="admin@acme-stream.io"
    )
    create_resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Checkout down", "service": "checkout-service", "severity": "sev2"},
        headers=_auth_headers(token),
    )
    incident_id = create_resp.json()["id"]

    app.dependency_overrides[get_agent_llm] = lambda: _trivial_fake_llm("unresolved")

    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate/stream", headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = []
    for block in resp.text.strip().split("\n\n"):
        lines = block.splitlines()
        event_name = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append((event_name, data))

    assert events[-1][0] == "report"
    assert events[-1][1]["outcome"] == "unresolved"
    node_events = [data["node"] for name, data in events if name == "node_complete"]
    assert "intake" in node_events
    assert "plan" in node_events
    assert "report" in node_events


async def test_investigate_returns_503_on_unexpected_llm_failure(client: AsyncClient) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-llm-down", admin_email="admin@acme-llm-down.io"
    )
    create_resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Checkout down", "service": "checkout-service", "severity": "sev2"},
        headers=_auth_headers(token),
    )
    incident_id = create_resp.json()["id"]

    class RaisingFakeLLM:
        async def call_with_tools(self, messages, tools):
            raise RuntimeError("Groq API unreachable: connection refused")

        async def call_structured(self, messages, schema):
            raise RuntimeError("Groq API unreachable: connection refused")

    app.dependency_overrides[get_agent_llm] = lambda: RaisingFakeLLM()

    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate", headers=_auth_headers(token)
    )
    assert resp.status_code == 503
    assert "connection refused" not in resp.text
    assert "temporarily unavailable" in resp.json()["detail"]


async def test_investigate_returns_503_when_llm_not_configured(client: AsyncClient) -> None:
    """Distinct from the test above: this one does NOT override
    get_agent_llm, so it exercises the real dependency's own fallback —
    caught live during manual testing, where a blank GROQ_API_KEY made
    ChatOpenAI's constructor raise during dependency resolution (before
    the route's own try/except could ever run), surfacing as a bare 500
    with an internal OpenAI SDK traceback instead of a clean response.
    conftest.py forces GROQ_API_KEY="" for the whole test session.
    """
    app.dependency_overrides.pop(get_agent_llm, None)
    token = await _register_and_login(
        client, tenant_slug="acme-llm-unconfigured", admin_email="admin@acme-llm-unconfigured.io"
    )
    create_resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Checkout down", "service": "checkout-service", "severity": "sev2"},
        headers=_auth_headers(token),
    )
    incident_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate", headers=_auth_headers(token)
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


async def test_investigate_rate_limit_returns_429_once_exhausted(client: AsyncClient) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-ratelimit", admin_email="admin@acme-ratelimit.io"
    )
    me = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    user_id = me.json()["id"]

    create_resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Checkout down", "service": "checkout-service", "severity": "sev2"},
        headers=_auth_headers(token),
    )
    incident_id = create_resp.json()["id"]

    # Pre-exhaust the limit directly rather than running 10 full fake
    # investigations — the rate limit dependency runs before the route
    # body either way, so this exercises the same wiring more cheaply.
    redis = get_redis_client()
    key = f"ratelimit:investigate:user:{user_id}"
    await redis.set(key, 10, ex=60)

    app.dependency_overrides[get_agent_llm] = lambda: _trivial_fake_llm("unresolved")
    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate", headers=_auth_headers(token)
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers

    await redis.delete(key)


async def test_tenant_id_is_bound_into_logs_during_an_authenticated_request(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-log-context", admin_email="admin@acme-log-context.io"
    )
    me = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    tenant_id = me.json()["tenant_id"]

    create_resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Checkout down", "service": "checkout-service", "severity": "sev2"},
        headers=_auth_headers(token),
    )
    incident_id = create_resp.json()["id"]

    app.dependency_overrides[get_agent_llm] = lambda: _trivial_fake_llm("unresolved")

    with structlog.testing.capture_logs() as captured:
        resp = await client.post(
            f"/api/v1/incidents/{incident_id}/investigate", headers=_auth_headers(token)
        )
    assert resp.status_code == 200

    tool_call_logs = [entry for entry in captured if entry.get("event") == "tool_call_succeeded"]
    assert tool_call_logs
    assert all(entry.get("tenant_id") == tenant_id for entry in tool_call_logs)
