from httpx import AsyncClient

REGISTER_PAYLOAD = {
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme-api-memories",
    "admin_email": "admin@acme-memories.io",
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


async def test_memories_require_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/memories")
    assert resp.status_code == 401


async def test_set_profile_preference_and_list(client: AsyncClient) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-mem-profile", admin_email="admin@acme-mem-profile.io"
    )

    set_resp = await client.put(
        "/api/v1/memories/profile",
        json={"content": "Prefers concise reports with evidence first."},
        headers=_auth_headers(token),
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["memory_type"] == "profile"

    list_resp = await client.get("/api/v1/memories", headers=_auth_headers(token))
    assert list_resp.status_code == 200
    contents = [m["content"] for m in list_resp.json()]
    assert "Prefers concise reports with evidence first." in contents


async def test_set_profile_preference_rejects_secret_content(client: AsyncClient) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-mem-secret", admin_email="admin@acme-mem-secret.io"
    )
    resp = await client.put(
        "/api/v1/memories/profile",
        json={"content": "my api_key: sk-abcdefghij1234567890klmnop is important"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 422


async def test_setting_profile_preference_twice_supersedes_not_duplicates(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-mem-resupersede", admin_email="admin@acme-mem-resupersede.io"
    )
    await client.put(
        "/api/v1/memories/profile",
        json={"content": "Prefers concise reports with evidence first."},
        headers=_auth_headers(token),
    )
    await client.put(
        "/api/v1/memories/profile",
        json={"content": "Prefers concise reports with evidence first."},
        headers=_auth_headers(token),
    )

    list_resp = await client.get("/api/v1/memories", headers=_auth_headers(token))
    profile_memories = [m for m in list_resp.json() if m["memory_type"] == "profile"]
    assert len(profile_memories) == 1


async def test_delete_memory(client: AsyncClient) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-mem-delete", admin_email="admin@acme-mem-delete.io"
    )
    set_resp = await client.put(
        "/api/v1/memories/profile",
        json={"content": "Prefers concise reports with evidence first."},
        headers=_auth_headers(token),
    )
    memory_id = set_resp.json()["id"]

    delete_resp = await client.delete(
        f"/api/v1/memories/{memory_id}", headers=_auth_headers(token)
    )
    assert delete_resp.status_code == 204

    list_resp = await client.get("/api/v1/memories", headers=_auth_headers(token))
    assert all(m["id"] != memory_id for m in list_resp.json())


async def test_correct_memory_supersedes_the_targeted_record(client: AsyncClient) -> None:
    token = await _register_and_login(
        client, tenant_slug="acme-mem-correct", admin_email="admin@acme-mem-correct.io"
    )
    set_resp = await client.put(
        "/api/v1/memories/profile",
        json={"content": "Prefers verbose reports."},
        headers=_auth_headers(token),
    )
    memory_id = set_resp.json()["id"]

    correct_resp = await client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"content": "Prefers concise reports with evidence first."},
        headers=_auth_headers(token),
    )
    assert correct_resp.status_code == 200
    corrected_id = correct_resp.json()["id"]
    assert corrected_id != memory_id

    list_resp = await client.get("/api/v1/memories", headers=_auth_headers(token))
    ids = [m["id"] for m in list_resp.json()]
    assert memory_id not in ids
    assert corrected_id in ids


async def test_user_cannot_delete_another_users_profile_memory(client: AsyncClient) -> None:
    token_a = await _register_and_login(
        client, tenant_slug="acme-mem-tenant-a", admin_email="admin@mem-tenant-a.io"
    )
    set_resp = await client.put(
        "/api/v1/memories/profile",
        json={"content": "Prefers concise reports with evidence first."},
        headers=_auth_headers(token_a),
    )
    memory_id = set_resp.json()["id"]

    token_b = await _register_and_login(
        client, tenant_slug="acme-mem-tenant-b", admin_email="admin@mem-tenant-b.io"
    )
    delete_resp = await client.delete(
        f"/api/v1/memories/{memory_id}", headers=_auth_headers(token_b)
    )
    # Cross-tenant: the record isn't even visible, so it's a 404, not a 403.
    assert delete_resp.status_code == 404
