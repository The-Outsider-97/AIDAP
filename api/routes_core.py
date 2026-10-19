"""Public, authentication, account and team endpoints."""

from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse

from ..contracts import requests as R
from ..contracts.versions import CONTRACTS
from ..domain.evaluations import CHECK_CATALOG
from ..domain.governance.authorization import Permission, ROLE_PERMISSIONS, Role
from ..version import API_VERSION, SLAI_BASELINE_COMMIT, __version__
from .http import Ctx, Reply, api, set_session_cookies


def _login_reply(c: Ctx, res: dict[str, Any], status: int = 200) -> Reply:
    st = c.svc.deps.settings
    age = st.session_hours * 3600
    base = {"max_age": age, "secure": st.cookie_secure, "samesite": "lax", "path": "/"}
    return Reply({"csrf_token": res["csrf_token"], "me": c.svc.auth.me(res["principal"])}, status,
                 cookies=[{"key": "aidap_session", "value": res["session_token"], "httponly": True, **base},
                          {"key": "aidap_csrf", "value": res["csrf_token"], "httponly": False, **base}])


# ------------------------------------------------------------------ public
@api("GET", "/health", public=True, rate="none")
def health(c: Ctx) -> Any:
    return {"status": "ok", "version": __version__}


@api("GET", "/health/ready", public=True, rate="none")
def ready(c: Ctx) -> Any:
    d = c.svc.deps
    checks: dict[str, Any] = {}
    try:
        d.db.count("tenants")
        checks["database"] = {"ok": True}
    except Exception as exc:                                           # noqa: BLE001
        checks["database"] = {"ok": False, "error": type(exc).__name__}
    checks["queue"] = {"ok": True, **d.queue.stats()}
    checks["malware_scanner"] = d.scanner.health()
    checks["billing"] = d.billing.health()
    checks["mail"] = {"ok": True, "backend": getattr(d.mailer, "backend_name", "")}
    slai = d.slai.health() if d.slai is not None else {"enabled": False}
    ok = all(v.get("ok", True) for k, v in checks.items() if k in ("database", "queue"))
    return Reply({"status": "ready" if ok else "degraded", "version": __version__, "checks": checks, "slai": slai},
                 200 if ok else 503)


@api("GET", "/meta", public=True)
def meta(c: Ctx) -> Any:
    return {"name": "AIDAP", "version": __version__, "api_version": API_VERSION, "contracts": CONTRACTS,
            "slai_baseline_commit": SLAI_BASELINE_COMMIT, "business_email": c.svc.deps.settings.business_email,
            "billing_provider": c.svc.deps.billing.provider, "environment": c.svc.deps.settings.environment,
            "sandbox_billing": c.svc.deps.billing.provider == "sandbox"}


@api("GET", "/plans", public=True)
def plans(c: Ctx) -> Any:
    return c.svc.billing.catalog()


@api("GET", "/catalog/checks", public=True)
def check_catalog(c: Ctx) -> Any:
    return [{"id": s.id, "category": s.category.value, "stage": s.stage, "title": s.title, "method": s.method,
             "description": s.description, "default_mandatory": s.default_mandatory, "origin": s.origin.value,
             "external": s.external, "needs_baseline": s.needs_baseline,
             "failure_class": s.failure_class.value if s.failure_class else None} for s in CHECK_CATALOG.values()]


@api("GET", "/catalog/roles", public=True)
def role_catalog(c: Ctx) -> Any:
    return {r.value: sorted(p.value for p in ROLE_PERMISSIONS[r]) for r in Role}


@api("GET", "/catalog/templates", public=True)
def templates(c: Ctx) -> Any:
    cat = c.svc.deps.catalog
    return {"profiles": cat.summaries("profile"), "policies": cat.summaries("policy")}


@api("POST", "/contact", public=True, body=R.CONTACT)
def contact(c: Ctx) -> Any:
    return Reply(c.svc.contact.submit(c.body, c.ip), 202)


@api("POST", "/webhooks/stripe", public=True, payload="raw", rate="none")
def stripe_webhook(c: Ctx) -> Any:
    out = c.svc.billing.handle_webhook(c.raw, c.req.headers.get("stripe-signature", ""))
    return {"received": True, **{k: v for k, v in out.items() if k in ("handled", "duplicate")}}


# ------------------------------------------------------------------ auth
@api("POST", "/auth/signup", public=True, body=R.SIGNUP)
def signup(c: Ctx) -> Any:
    b = c.body
    res = c.svc.auth.signup(email=b["email"], name=b["name"], password=b["password"], organization=b["organization"],
                            accept_terms=b["accept_terms"], ip=c.ip, ua=c.ua)
    return _login_reply(c, res, 201)


@api("POST", "/auth/login", public=True, body=R.LOGIN)
def login(c: Ctx) -> Any:
    b = c.body
    return _login_reply(c, c.svc.auth.login(email=b["email"], password=b["password"], code=b.get("code", ""), ip=c.ip, ua=c.ua))


@api("POST", "/auth/logout")
def logout(c: Ctx) -> Any:
    c.svc.auth.logout(c.principal)
    return Reply({"ok": True}, delete_cookies=["aidap_session", "aidap_csrf"])


@api("POST", "/auth/password/reset-request", public=True, body=R.PASSWORD_RESET_REQUEST)
def reset_request(c: Ctx) -> Any:
    c.svc.auth.request_reset(c.body["email"], c.ip)
    return Reply({"ok": True, "message": "If that address has an account, a reset link is on its way."}, 202)


@api("POST", "/auth/password/reset-confirm", public=True, body=R.PASSWORD_RESET_CONFIRM)
def reset_confirm(c: Ctx) -> Any:
    c.svc.auth.confirm_reset(c.body["token"], c.body["new_password"])
    return {"ok": True}


@api("POST", "/auth/invitations/accept", public=True, body=R.INVITE_ACCEPT)
def accept_invite(c: Ctx) -> Any:
    b = c.body
    return _login_reply(c, c.svc.auth.accept_invitation(b["token"], b.get("name", ""), b.get("password", ""), ip=c.ip, ua=c.ua), 201)


@api("GET", "/me")
def me(c: Ctx) -> Any:
    return c.svc.auth.me(c.principal)


@api("POST", "/me/switch-tenant", body={"tenant_id": R.s(80, required=True)})
def switch_tenant(c: Ctx) -> Any:
    return _login_reply(c, c.svc.auth.switch_tenant(c.principal, c.body["tenant_id"], ip=c.ip, ua=c.ua))


@api("POST", "/auth/csrf")
def csrf(c: Ctx) -> Any:
    tok = c.svc.auth.rotate_csrf(c.principal)
    st = c.svc.deps.settings
    return Reply({"csrf_token": tok}, cookies=[{"key": "aidap_csrf", "value": tok, "max_age": st.session_hours * 3600,
                                                 "httponly": False, "secure": st.cookie_secure, "samesite": "lax", "path": "/"}])


@api("POST", "/auth/password/change", body=R.PASSWORD_CHANGE)
def password_change(c: Ctx) -> Any:
    c.svc.auth.change_password(c.principal, c.body["current_password"], c.body["new_password"])
    return {"ok": True}


@api("POST", "/auth/mfa/setup")
def mfa_setup(c: Ctx) -> Any:
    return c.svc.auth.mfa_setup(c.principal)


@api("POST", "/auth/mfa/enable", body=R.MFA_CODE)
def mfa_enable(c: Ctx) -> Any:
    return c.svc.auth.mfa_enable(c.principal, c.body["code"])


@api("POST", "/auth/mfa/disable", body=R.MFA_DISABLE)
def mfa_disable(c: Ctx) -> Any:
    c.svc.auth.mfa_disable(c.principal, c.body["code"], c.body["password"])
    return {"ok": True}


# ------------------------------------------------------------------ team
@api("PATCH", "/tenant", body=R.TENANT_UPDATE)
def tenant_update(c: Ctx) -> Any:
    b = c.body
    return c.svc.auth.update_tenant(c.principal, b.get("name") or None, b.get("retention_days"), "retention_days" in c.present,
                                    b.get("review_sla_hours") if "review_sla_hours" in c.present else None)


@api("GET", "/members")
def members(c: Ctx) -> Any:
    return c.svc.auth.list_members(c.principal)


@api("PATCH", "/members/{member_id}", body=R.MEMBER_UPDATE)
def member_update(c: Ctx) -> Any:
    return c.svc.auth.update_member(c.principal, c.params["member_id"], c.body["role"], c.body.get("project_ids") or [])


@api("DELETE", "/members/{member_id}")
def member_remove(c: Ctx) -> Any:
    c.svc.auth.remove_member(c.principal, c.params["member_id"])
    return Reply(None, 200)


@api("GET", "/invitations")
def invitations(c: Ctx) -> Any:
    return c.svc.auth.list_invitations(c.principal)


@api("POST", "/invitations", body=R.INVITE_CREATE)
def invite(c: Ctx) -> Any:
    return Reply(c.svc.auth.invite(c.principal, c.body["email"], c.body["role"], c.body.get("project_ids") or []), 201)


@api("DELETE", "/invitations/{inv_id}")
def invitation_revoke(c: Ctx) -> Any:
    c.svc.auth.revoke_invitation(c.principal, c.params["inv_id"])
    return {"ok": True}


@api("GET", "/api-keys")
def api_keys(c: Ctx) -> Any:
    return c.svc.auth.list_api_keys(c.principal)


@api("POST", "/api-keys", body=R.API_KEY_CREATE)
def api_key_create(c: Ctx) -> Any:
    b = c.body
    return Reply(c.svc.auth.create_api_key(c.principal, b["name"], b["scopes"], b.get("project_ids") or [], b.get("expires_in_days")), 201)


@api("DELETE", "/api-keys/{key_id}")
def api_key_revoke(c: Ctx) -> Any:
    c.svc.auth.revoke_api_key(c.principal, c.params["key_id"])
    return {"ok": True}
