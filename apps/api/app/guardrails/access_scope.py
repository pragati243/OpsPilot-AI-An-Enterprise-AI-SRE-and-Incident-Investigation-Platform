from app.models.user import User

PUBLIC_SCOPE = "public"


def allowed_scopes_for(user: User) -> set[str]:
    """Scopes this user can see documents under. A document with an empty
    access_scope is public to the whole tenant; otherwise it must be tagged
    with the caller's role (or "public") to be visible. This is intentionally
    simple role-based ACL groundwork for the retrieval phase, not the final
    access model.
    """
    return {PUBLIC_SCOPE, user.role.value}
