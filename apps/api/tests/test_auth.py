from httpx import AsyncClient

REGISTER_PAYLOAD = {
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme",
    "admin_email": "admin@acme-corp.io",
    "admin_password": "correct-horse-battery",
    "admin_full_name": "Ada Admin",
}


async def _register(client: AsyncClient, **overrides: str) -> dict:
    payload = {**REGISTER_PAYLOAD, **overrides}
    response = await client.post("/api/v1/auth/register-tenant", json=payload)
    return response


async def test_register_tenant_creates_admin_user(client: AsyncClient) -> None:
    response = await _register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == REGISTER_PAYLOAD["admin_email"]
    assert body["role"] == "admin"
    assert "hashed_password" not in body


async def test_register_tenant_duplicate_slug_conflicts(client: AsyncClient) -> None:
    await _register(client)
    response = await _register(client, admin_email="someone-else@acme-corp.io")
    assert response.status_code == 409


async def test_register_tenant_duplicate_email_conflicts(client: AsyncClient) -> None:
    await _register(client)
    response = await _register(client, tenant_slug="acme-2", tenant_name="Acme Two")
    assert response.status_code == 409


async def test_login_success_returns_tokens(client: AsyncClient) -> None:
    await _register(client)
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["admin_email"],
            "password": REGISTER_PAYLOAD["admin_password"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_wrong_password_rejected(client: AsyncClient) -> None:
    await _register(client)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["admin_email"], "password": "wrong-password"},
    )
    assert response.status_code == 401


async def test_login_unknown_email_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@acme-corp.io", "password": "whatever12345"},
    )
    assert response.status_code == 401


async def test_me_requires_valid_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_me_returns_current_user_for_valid_token(client: AsyncClient) -> None:
    await _register(client)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["admin_email"],
            "password": REGISTER_PAYLOAD["admin_password"],
        },
    )
    access_token = login_response.json()["access_token"]

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == REGISTER_PAYLOAD["admin_email"]


async def test_refresh_token_issues_new_access_token(client: AsyncClient) -> None:
    await _register(client)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["admin_email"],
            "password": REGISTER_PAYLOAD["admin_password"],
        },
    )
    refresh_token = login_response.json()["refresh_token"]

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_refresh_rejects_access_token_used_as_refresh(client: AsyncClient) -> None:
    await _register(client)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["admin_email"],
            "password": REGISTER_PAYLOAD["admin_password"],
        },
    )
    access_token = login_response.json()["access_token"]

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": access_token}
    )
    assert response.status_code == 401
