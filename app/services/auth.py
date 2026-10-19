"""Accounts, sessions, MFA, invitations, members and API keys."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from ...domain.accounts.models import SubscriptionStatus
from ...domain.accounts.plans import F_API, F_REVIEW_ROLES
from ...domain.governance.authorization import Permission, ROLE_PERMISSIONS, Role, SCOPE_PERMISSIONS
from ...domain.utils.domain_errors import (Conflict, Forbidden, NotFound, RateLimited, Unauthenticated, ValidationFailed)
from ...domain.utils.domain_helpers import iso, new_id, parse_iso, slugify
from ..context import Principal
from ..utils.common import audit, audit_system, sanitize_doc
from .notify import NotificationService
from .plans import PlanService

__all__ = ["AuthService", "SESSION_COOKIE", "CSRF_COOKIE"]

SESSION_COOKIE = "aidap_session"
CSRF_COOKIE = "aidap_csrf"
_RECOVERY_CODES = 10


class AuthService:
    def __init__(self, deps: Any, plans: PlanService, notify: NotificationService) -> None:
        self.d, self.plans, self.notify = deps, plans, notify

    # ------------------------------------------------------------------ helpers
    def _user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.d.db.get_by_ukey("users", f"email:{email.lower()}")

    def _memberships(self, user_id: str) -> list[dict[str, Any]]:
        return self.d.db.find("memberships", where={"user_id": user_id}, order_by="created_at", desc=False, limit=100)

    def _throttle(self, key: str) -> None:
        ok, retry = self.d.login_limiter.check(key)
        if not ok:
            raise RateLimited("too many attempts; try again shortly", details={"retry_after": round(retry, 1)})

    def _principal(self, user: dict[str, Any], membership: dict[str, Any], session_id: str = "", ip: str = "") -> Principal:
        return Principal.for_user(user_id=user["id"], email=user["email"], name=user["name"], tenant_id=membership["tenant_id"],
                                  role=membership["role"], project_ids=membership.get("project_ids", []),
                                  session_id=session_id, ip=ip)

    def _new_session(self, user: dict[str, Any], tenant_id: str, ip: str, ua: str, mfa_passed: bool) -> tuple[str, str, dict[str, Any]]:
        token, digest = self.d.tokens.new("aidap_s")
        csrf, csrf_digest = self.d.tokens.new("aidap_c", 24)
        now = self.d.now()
        rec = {"id": new_id("ses"), "user_id": user["id"], "digest": digest, "csrf_digest": csrf_digest,
               "created_at": iso(now), "expires_at": iso(now + timedelta(hours=self.d.settings.session_hours)),
               "tenant_id": tenant_id, "ip": ip[:64], "user_agent": ua[:200], "mfa_passed": mfa_passed, "revoked_at": None}
        self.d.db.insert("sessions", rec, tenant_id=tenant_id, ukey=f"digest:{digest}")
        return token, csrf, rec

    # ------------------------------------------------------------------ sign-up / login
    def signup(self, *, email: str, name: str, password: str, organization: str, accept_terms: bool, ip: str = "",
               ua: str = "") -> dict[str, Any]:
        self._throttle(f"signup:{ip}")
        if not accept_terms:
            raise ValidationFailed("you must accept the terms to create an account", details={"fields": {"accept_terms": "must be accepted"}})
        self.d.passwords.validate(password)
        email = email.lower()
        if self._user_by_email(email):
            raise Conflict("an account with this email already exists", code="email_taken")
        salt, digest = self.d.passwords.hash(password)
        now = self.d.now()
        uid, tid = new_id("usr"), new_id("ten")
        user = {"id": uid, "email": email, "name": name, "password_salt": salt, "password_hash": digest,
                "created_at": iso(now), "email_verified": False, "failed_attempts": 0, "locked_until": None,
                "last_login_at": iso(now), "mfa_enabled": False, "mfa_secret_sealed": "", "mfa_last_counter": 0,
                "recovery_hashes": [], "disabled": False}
        slug = slugify(organization, "org")
        if self.d.db.get_by_ukey("tenants", f"slug:{slug}"):
            slug = f"{slug}-{secrets.token_hex(2)}"
        tenant = {"id": tid, "name": organization, "slug": slug, "created_at": iso(now), "owner_user_id": uid,
                  "billing_email": email, "retention_days": None, "settings": {}, "suspended": False, "deleted_at": None}
        member = {"id": new_id("mem"), "tenant_id": tid, "user_id": uid, "role": "owner", "created_at": iso(now), "project_ids": []}
        with self.d.db.transaction():
            if not self.d.db.insert("users", user, ukey=f"email:{email}"):
                raise Conflict("an account with this email already exists", code="email_taken")
            self.d.db.insert("tenants", tenant, tenant_id=tid, ukey=f"slug:{slug}")
            self.d.db.insert("memberships", member, tenant_id=tid, ukey=f"{tid}:{uid}")
            self.plans.subscription(tid)
            proj = self._default_project(tid, now)
        audit_system(self.d, tid, "account.created", uid, {"email": email, "organization": organization}, actor=email)
        self.notify.email(tid, email, "Welcome to AIDAP",
                          f"Hello {name},\n\nYour AIDAP workspace '{organization}' is ready: {self.d.settings.base_url}/app\n\n"
                          "AIDAP validates what enters your AI systems. Start by submitting an input to the "
                          f"'{proj['name']}' project.\n", dedupe_key=f"welcome:{uid}")
        token, csrf, ses = self._new_session(user, tid, ip, ua, True)
        return {"session_token": token, "csrf_token": csrf, "session": ses,
                "principal": self._principal(user, member, ses["id"], ip), "user": sanitize_doc(user), "tenant": tenant}

    def _default_project(self, tid: str, now: Any) -> dict[str, Any]:
        proj = {"id": new_id("prj"), "tenant_id": tid, "name": "My first project", "slug": "my-first-project",
                "created_at": iso(now), "description": "Starter project created with your workspace.",
                "default_profile_id": "rag_indexing", "default_policy_id": "standard", "default_destination_id": "",
                "archived": False}
        self.d.db.insert("projects", proj, tenant_id=tid)
        return proj

    def login(self, *, email: str, password: str, code: str = "", ip: str = "", ua: str = "") -> dict[str, Any]:
        email = email.lower()
        self._throttle(f"login:{ip}")
        self._throttle(f"login-email:{email}")
        user = self._user_by_email(email)
        now = self.d.now()
        if user is None:
            self.d.passwords.verify(password, "00" * 16, "00" * 64)          # equalise timing
            raise Unauthenticated("invalid email or password", code="invalid_credentials")
        locked = parse_iso(user.get("locked_until"))
        if user.get("disabled"):
            raise Unauthenticated("this account is disabled", code="account_disabled")
        if locked and now < locked:
            raise Unauthenticated("too many failed attempts; the account is temporarily locked", code="account_locked",
                                  details={"retry_after_seconds": int((locked - now).total_seconds())})
        if not self.d.passwords.verify(password, user["password_salt"], user["password_hash"]):
            user["failed_attempts"] = int(user.get("failed_attempts", 0)) + 1
            if user["failed_attempts"] >= self.d.settings.lockout_attempts:
                user["locked_until"] = iso(now + timedelta(minutes=self.d.settings.lockout_minutes))
                user["failed_attempts"] = 0
            self.d.db.put("users", user)
            raise Unauthenticated("invalid email or password", code="invalid_credentials")
        if user.get("mfa_enabled"):
            if not code:
                raise Unauthenticated("a verification code is required", code="mfa_required")
            if not self._check_second_factor(user, code):
                user["failed_attempts"] = int(user.get("failed_attempts", 0)) + 1
                self.d.db.put("users", user)
                raise Unauthenticated("the verification code is not valid", code="mfa_invalid")
        members = self._memberships(user["id"])
        if not members:
            raise Forbidden("this account does not belong to any workspace", code="no_membership")
        tenant_pref = user.get("last_tenant_id")
        member = next((m for m in members if m["tenant_id"] == tenant_pref), members[0])
        user["failed_attempts"], user["locked_until"], user["last_login_at"] = 0, None, iso(now)
        user["last_tenant_id"] = member["tenant_id"]
        self.d.db.put("users", user)
        token, csrf, ses = self._new_session(user, member["tenant_id"], ip, ua, True)
        audit_system(self.d, member["tenant_id"], "auth.login", user["id"], {"ip": ip, "mfa": bool(user.get("mfa_enabled"))},
                     actor=email)
        return {"session_token": token, "csrf_token": csrf, "session": ses,
                "principal": self._principal(user, member, ses["id"], ip), "user": sanitize_doc(user)}

    def _check_second_factor(self, user: dict[str, Any], code: str) -> bool:
        secret = self.d.box.open(user["mfa_secret_sealed"], aad=user["id"].encode()).decode()
        counter = self.d.totp.verify(secret, code, last_counter=int(user.get("mfa_last_counter", 0)), now=self.d.now())
        if counter is not None:
            user["mfa_last_counter"] = counter                      # replay guard: a code works once
            self.d.db.put("users", user)
            return True
        digest = self.d.tokens.digest(code.strip().lower().replace("-", ""))
        if digest in user.get("recovery_hashes", []):
            user["recovery_hashes"] = [h for h in user["recovery_hashes"] if h != digest]
            self.d.db.put("users", user)
            return True
        return False

    def logout(self, p: Principal) -> None:
        if p.session_id:
            ses = self.d.db.get("sessions", p.session_id)
            if ses and not ses.get("revoked_at"):
                ses["revoked_at"] = iso(self.d.now())
                self.d.db.put("sessions", ses, tenant_id=ses.get("tenant_id", ""))
        audit(self.d, p, "auth.logout", p.id)

    # ------------------------------------------------------------------ authentication of requests
    def authenticate_session(self, token: str, csrf: str | None, *, unsafe_method: bool, ip: str = "") -> Principal:
        if not token or not token.startswith("aidap_s_"):
            raise Unauthenticated("sign in required", code="unauthenticated")
        ses = self.d.db.get_by_ukey("sessions", f"digest:{self.d.tokens.digest(token)}")
        now = self.d.now()
        if ses is None or ses.get("revoked_at") or now >= parse_iso(ses["expires_at"]):
            raise Unauthenticated("your session has expired; sign in again", code="session_expired")
        if unsafe_method and self.d.settings.csrf:
            if not csrf or not self.d.tokens.equal(self.d.tokens.digest(csrf), ses["csrf_digest"]):
                raise Forbidden("missing or invalid CSRF token", code="csrf_failed")
        user = self.d.db.get("users", ses["user_id"])
        if user is None or user.get("disabled"):
            raise Unauthenticated("account unavailable", code="account_disabled")
        member = self.d.db.get_by_ukey("memberships", f"{ses['tenant_id']}:{ses['user_id']}")
        if member is None:
            raise Forbidden("you are no longer a member of this workspace", code="no_membership")
        tenant = self.d.db.get("tenants", ses["tenant_id"], tenant_id=ses["tenant_id"])
        if tenant is None or tenant.get("suspended") or tenant.get("deleted_at"):
            raise Forbidden("this workspace is suspended", code="tenant_suspended")
        return self._principal(user, member, ses["id"], ip)

    def authenticate_api_key(self, token: str, ip: str = "") -> Principal:
        parts = token.split("_", 2)
        if len(parts) != 3 or parts[0] != "aidk" or len(parts[1]) != 10:
            raise Unauthenticated("invalid API key", code="invalid_api_key")
        rec = self.d.db.get_by_ukey("api_keys", f"prefix:{parts[1]}")
        if rec is None or not self.d.tokens.equal(self.d.tokens.digest(token), rec["digest"]):
            raise Unauthenticated("invalid API key", code="invalid_api_key")
        now = self.d.now()
        if rec.get("revoked_at") or (rec.get("expires_at") and now >= parse_iso(rec["expires_at"])):
            raise Unauthenticated("this API key is revoked or expired", code="invalid_api_key")
        tenant = self.d.db.get("tenants", rec["tenant_id"], tenant_id=rec["tenant_id"])
        if tenant is None or tenant.get("suspended") or tenant.get("deleted_at"):
            raise Forbidden("this workspace is suspended", code="tenant_suspended")
        plan = self.plans.plan_for(rec["tenant_id"])
        if not plan.has(F_API):
            raise Forbidden("API access is not included in the current plan", code="feature_not_in_plan")
        last = parse_iso(rec.get("last_used_at"))
        if last is None or (now - last).total_seconds() > 300:       # avoid a write per request
            rec["last_used_at"] = iso(now)
            self.d.db.put("api_keys", rec, tenant_id=rec["tenant_id"])
        return Principal.for_api_key(key_id=rec["id"], name=rec["name"], tenant_id=rec["tenant_id"], scopes=rec["scopes"],
                                     project_ids=rec.get("project_ids", []), ip=ip)

    # ------------------------------------------------------------------ profile / password / tenant switching
    def me(self, p: Principal) -> dict[str, Any]:
        user = self.d.db.get("users", p.id) if p.kind == "user" else None
        mems = []
        for m in self._memberships(p.id) if p.kind == "user" else []:
            t = self.d.db.get("tenants", m["tenant_id"], tenant_id=m["tenant_id"]) or {}
            mems.append({"tenant_id": m["tenant_id"], "tenant_name": t.get("name", ""), "role": m["role"],
                         "current": m["tenant_id"] == p.tenant_id})
        tenant = self.d.db.get("tenants", p.tenant_id, tenant_id=p.tenant_id) or {}
        plan = self.plans.plan_for(p.tenant_id)
        sub = self.plans.subscription(p.tenant_id)
        return {"user": sanitize_doc(user) if user else {"id": p.id, "name": p.name, "kind": p.kind},
                "role": p.role, "permissions": sorted(x.value for x in p.permissions), "tenant": sanitize_doc(tenant),
                "memberships": mems, "plan": plan.to_dict(), "subscription_status": sub.get("status"),
                "billing_provider": self.d.billing.provider, "mfa_enabled": bool(user and user.get("mfa_enabled"))}

    def switch_tenant(self, p: Principal, tenant_id: str, ip: str = "", ua: str = "") -> dict[str, Any]:
        user = self.d.db.get("users", p.id)
        member = next((m for m in self._memberships(p.id) if m["tenant_id"] == tenant_id), None)
        if user is None or member is None:
            raise Forbidden("you are not a member of that workspace", code="no_membership")
        self.logout(p)
        user["last_tenant_id"] = tenant_id
        self.d.db.put("users", user)
        token, csrf, ses = self._new_session(user, tenant_id, ip, ua, True)
        return {"session_token": token, "csrf_token": csrf, "session": ses, "principal": self._principal(user, member, ses["id"], ip)}

    def rotate_csrf(self, p: Principal) -> str:
        ses = self.d.db.get("sessions", p.session_id)
        if ses is None:
            raise Unauthenticated("sign in required")
        csrf, digest = self.d.tokens.new("aidap_c", 24)
        ses["csrf_digest"] = digest
        self.d.db.put("sessions", ses, tenant_id=ses.get("tenant_id", ""))
        return csrf

    def change_password(self, p: Principal, current: str, new: str) -> None:
        user = self.d.db.get("users", p.id)
        if user is None or not self.d.passwords.verify(current, user["password_salt"], user["password_hash"]):
            raise Unauthenticated("the current password is not correct", code="invalid_credentials")
        self.d.passwords.validate(new)
        user["password_salt"], user["password_hash"] = self.d.passwords.hash(new)
        self.d.db.put("users", user)
        self._revoke_sessions(p.id, except_id=p.session_id)
        audit(self.d, p, "auth.password_changed", p.id)

    def _revoke_sessions(self, user_id: str, except_id: str = "") -> int:
        n = 0
        for s in self.d.db.find("sessions", where={"user_id": user_id, "revoked_at": None}, limit=500):
            if s["id"] != except_id:
                s["revoked_at"] = iso(self.d.now())
                self.d.db.put("sessions", s, tenant_id=s.get("tenant_id", ""))
                n += 1
        return n

    def request_reset(self, email: str, ip: str = "") -> None:
        """Always succeeds from the caller's view: no account enumeration."""
        self._throttle(f"reset:{ip}")
        user = self._user_by_email(email)
        if user is None or user.get("disabled"):
            return
        token, digest = self.d.tokens.new("aidap_r", 32)
        rec = {"id": new_id("rst"), "user_id": user["id"], "digest": digest, "created_at": iso(self.d.now()),
               "expires_at": iso(self.d.now() + timedelta(hours=1)), "used_at": None}
        self.d.db.insert("resets", rec, ukey=f"digest:{digest}")
        m = self._memberships(user["id"])
        self.notify.email(m[0]["tenant_id"] if m else "", user["email"], "Reset your AIDAP password",
                          f"Use this link within one hour:\n{self.d.settings.base_url}/reset?token={token}\n\n"
                          "If you did not request this, ignore this message.", dedupe_key=f"reset:{rec['id']}")

    def confirm_reset(self, token: str, new_password: str) -> None:
        rec = self.d.db.get_by_ukey("resets", f"digest:{self.d.tokens.digest(token)}")
        if rec is None or rec.get("used_at") or self.d.now() >= parse_iso(rec["expires_at"]):
            raise ValidationFailed("this reset link is invalid or has expired", code="reset_invalid")
        self.d.passwords.validate(new_password)
        user = self.d.db.get("users", rec["user_id"])
        if user is None:
            raise ValidationFailed("this reset link is invalid or has expired", code="reset_invalid")
        user["password_salt"], user["password_hash"] = self.d.passwords.hash(new_password)
        user["failed_attempts"], user["locked_until"] = 0, None
        rec["used_at"] = iso(self.d.now())
        with self.d.db.transaction():
            self.d.db.put("users", user)
            self.d.db.put("resets", rec)
        self._revoke_sessions(user["id"])
        for m in self._memberships(user["id"]):
            audit_system(self.d, m["tenant_id"], "auth.password_reset", user["id"], actor=user["email"])

    # ------------------------------------------------------------------ MFA
    def mfa_setup(self, p: Principal) -> dict[str, Any]:
        user = self.d.db.get("users", p.id)
        if user is None:
            raise NotFound("user not found")
        if user.get("mfa_enabled"):
            raise Conflict("two-factor authentication is already enabled", code="mfa_already_enabled")
        secret = self.d.totp.new_secret()
        user["mfa_pending_sealed"] = self.d.box.seal(secret.encode(), aad=user["id"].encode())
        self.d.db.put("users", user)
        return {"secret": secret, "uri": self.d.totp.uri(secret, user["email"], self.d.settings.mfa_issuer)}

    def mfa_enable(self, p: Principal, code: str) -> dict[str, Any]:
        user = self.d.db.get("users", p.id)
        if user is None or not user.get("mfa_pending_sealed"):
            raise ValidationFailed("start two-factor setup first", code="mfa_not_started")
        secret = self.d.box.open(user["mfa_pending_sealed"], aad=user["id"].encode()).decode()
        counter = self.d.totp.verify(secret, code, now=self.d.now())
        if counter is None:
            raise ValidationFailed("that code is not valid", code="mfa_invalid")
        codes = [secrets.token_hex(5) for _ in range(_RECOVERY_CODES)]
        user.update({"mfa_enabled": True, "mfa_secret_sealed": self.d.box.seal(secret.encode(), aad=user["id"].encode()),
                     "mfa_last_counter": counter, "mfa_pending_sealed": "",
                     "recovery_hashes": [self.d.tokens.digest(c) for c in codes]})
        self.d.db.put("users", user)
        audit(self.d, p, "auth.mfa_enabled", p.id)
        return {"recovery_codes": [f"{c[:5]}-{c[5:]}" for c in codes]}

    def mfa_disable(self, p: Principal, code: str, password: str) -> None:
        user = self.d.db.get("users", p.id)
        if user is None or not user.get("mfa_enabled"):
            raise ValidationFailed("two-factor authentication is not enabled", code="mfa_not_enabled")
        if not self.d.passwords.verify(password, user["password_salt"], user["password_hash"]):
            raise Unauthenticated("the password is not correct", code="invalid_credentials")
        if not self._check_second_factor(user, code):
            raise ValidationFailed("that code is not valid", code="mfa_invalid")
        user.update({"mfa_enabled": False, "mfa_secret_sealed": "", "recovery_hashes": [], "mfa_last_counter": 0})
        self.d.db.put("users", user)
        audit(self.d, p, "auth.mfa_disabled", p.id)

    # ------------------------------------------------------------------ members & invitations
    def _check_role_allowed(self, tenant_id: str, role: str) -> None:
        if role in ("reviewer", "security"):
            self.plans.require_feature(tenant_id, F_REVIEW_ROLES, "Reviewer and security roles")

    def list_members(self, p: Principal) -> list[dict[str, Any]]:
        p.require(Permission.MEMBERS_MANAGE)
        out = []
        for m in self.d.db.find("memberships", tenant_id=p.tenant_id, order_by="created_at", desc=False, limit=500):
            u = self.d.db.get("users", m["user_id"]) or {}
            out.append({"id": m["id"], "user_id": m["user_id"], "email": u.get("email", ""), "name": u.get("name", ""),
                        "role": m["role"], "project_ids": m.get("project_ids", []), "mfa_enabled": bool(u.get("mfa_enabled")),
                        "last_login_at": u.get("last_login_at"), "created_at": m["created_at"]})
        return out

    def update_member(self, p: Principal, member_id: str, role: str, project_ids: list[str]) -> dict[str, Any]:
        p.require(Permission.MEMBERS_MANAGE)
        m = self.d.db.get("memberships", member_id, tenant_id=p.tenant_id)
        if m is None:
            raise NotFound("member not found")
        if m["role"] == "owner":
            raise Forbidden("the owner's role cannot be changed here", code="owner_protected")
        if role == "admin" and p.role != "owner":
            raise Forbidden("only the owner can grant the admin role", code="forbidden")
        self._check_role_allowed(p.tenant_id, role)
        m["role"], m["project_ids"] = role, project_ids
        self.d.db.put("memberships", m, tenant_id=p.tenant_id)
        audit(self.d, p, "member.updated", m["user_id"], {"role": role})
        return m

    def remove_member(self, p: Principal, member_id: str) -> None:
        p.require(Permission.MEMBERS_MANAGE)
        m = self.d.db.get("memberships", member_id, tenant_id=p.tenant_id)
        if m is None:
            raise NotFound("member not found")
        if m["role"] == "owner":
            raise Forbidden("the owner cannot be removed", code="owner_protected")
        self.d.db.delete("memberships", member_id, tenant_id=p.tenant_id)
        for s in self.d.db.find("sessions", where={"user_id": m["user_id"], "tenant_id": p.tenant_id, "revoked_at": None}, limit=200):
            s["revoked_at"] = iso(self.d.now())
            self.d.db.put("sessions", s, tenant_id=p.tenant_id)
        audit(self.d, p, "member.removed", m["user_id"])

    def invite(self, p: Principal, email: str, role: str, project_ids: list[str]) -> dict[str, Any]:
        p.require(Permission.MEMBERS_MANAGE)
        if role == "admin" and p.role != "owner":
            raise Forbidden("only the owner can invite an admin", code="forbidden")
        self._check_role_allowed(p.tenant_id, role)
        self.plans.enforce_seat_limit(p.tenant_id)
        email = email.lower()
        existing = self._user_by_email(email)
        if existing and any(m["tenant_id"] == p.tenant_id for m in self._memberships(existing["id"])):
            raise Conflict("this person is already a member", code="already_member")
        token, digest = self.d.tokens.new("aidap_i", 32)
        now = self.d.now()
        inv = {"id": new_id("inv"), "tenant_id": p.tenant_id, "email": email, "role": role, "digest": digest,
               "invited_by": p.actor, "created_at": iso(now),
               "expires_at": iso(now + timedelta(days=self.d.settings.invitation_days)), "accepted_at": None,
               "project_ids": project_ids}
        self.d.db.insert("invitations", inv, tenant_id=p.tenant_id, ukey=f"digest:{digest}")
        tenant = self.d.db.get("tenants", p.tenant_id, tenant_id=p.tenant_id) or {}
        self.notify.email(p.tenant_id, email, f"You're invited to {tenant.get('name', 'AIDAP')}",
                          f"{p.name or p.actor} invited you to join '{tenant.get('name', '')}' as {role}.\n"
                          f"Accept: {self.d.settings.base_url}/invite?token={token}\n(valid {self.d.settings.invitation_days} days)",
                          dedupe_key=f"invite:{inv['id']}")
        audit(self.d, p, "member.invited", email, {"role": role})
        return {**sanitize_doc(inv), "token": token if not self.d.settings.production else None}

    def list_invitations(self, p: Principal) -> list[dict[str, Any]]:
        p.require(Permission.MEMBERS_MANAGE)
        return [sanitize_doc(i) for i in self.d.db.find("invitations", tenant_id=p.tenant_id, where={"accepted_at": None}, limit=200)]

    def revoke_invitation(self, p: Principal, inv_id: str) -> None:
        p.require(Permission.MEMBERS_MANAGE)
        if not self.d.db.delete("invitations", inv_id, tenant_id=p.tenant_id):
            raise NotFound("invitation not found")
        audit(self.d, p, "member.invitation_revoked", inv_id)

    def accept_invitation(self, token: str, name: str, password: str, ip: str = "", ua: str = "") -> dict[str, Any]:
        self._throttle(f"invite:{ip}")
        inv = self.d.db.get_by_ukey("invitations", f"digest:{self.d.tokens.digest(token)}")
        if inv is None or inv.get("accepted_at") or self.d.now() >= parse_iso(inv["expires_at"]):
            raise ValidationFailed("this invitation is invalid or has expired", code="invitation_invalid")
        user = self._user_by_email(inv["email"])
        now = self.d.now()
        with self.d.db.transaction():
            if user is None:
                if not name or not password:
                    raise ValidationFailed("a name and password are required to create your account",
                                           details={"fields": {"name": "required", "password": "required"}})
                self.d.passwords.validate(password)
                salt, digest = self.d.passwords.hash(password)
                user = {"id": new_id("usr"), "email": inv["email"], "name": name, "password_salt": salt,
                        "password_hash": digest, "created_at": iso(now), "email_verified": True, "failed_attempts": 0,
                        "locked_until": None, "last_login_at": iso(now), "mfa_enabled": False, "mfa_secret_sealed": "",
                        "mfa_last_counter": 0, "recovery_hashes": [], "disabled": False}
                self.d.db.insert("users", user, ukey=f"email:{inv['email']}")
            elif not password or not self.d.passwords.verify(password, user["password_salt"], user["password_hash"]):
                raise Unauthenticated("enter the password of your existing AIDAP account to accept", code="invalid_credentials")
            member = {"id": new_id("mem"), "tenant_id": inv["tenant_id"], "user_id": user["id"], "role": inv["role"],
                      "created_at": iso(now), "project_ids": inv.get("project_ids", [])}
            if not self.d.db.insert("memberships", member, tenant_id=inv["tenant_id"], ukey=f"{inv['tenant_id']}:{user['id']}"):
                raise Conflict("you are already a member", code="already_member")
            inv["accepted_at"] = iso(now)
            self.d.db.put("invitations", inv, tenant_id=inv["tenant_id"])
        audit_system(self.d, inv["tenant_id"], "member.joined", user["id"], {"role": inv["role"]}, actor=user["email"])
        tok, csrf, ses = self._new_session(user, inv["tenant_id"], ip, ua, True)
        return {"session_token": tok, "csrf_token": csrf, "session": ses, "principal": self._principal(user, member, ses["id"], ip)}

    # ------------------------------------------------------------------ API keys
    def create_api_key(self, p: Principal, name: str, scopes: list[str], project_ids: list[str],
                       expires_in_days: int | None) -> dict[str, Any]:
        p.require(Permission.APIKEYS_MANAGE)
        self.plans.require_feature(p.tenant_id, F_API, "API access")
        bad = [s for s in scopes if s not in SCOPE_PERMISSIONS]
        if bad:
            raise ValidationFailed(f"unknown scope(s): {', '.join(bad)}")
        prefix = secrets.token_hex(5)
        secret = secrets.token_urlsafe(32)
        token = f"aidk_{prefix}_{secret}"
        now = self.d.now()
        rec = {"id": new_id("key"), "tenant_id": p.tenant_id, "name": name, "prefix": prefix,
               "digest": self.d.tokens.digest(token), "scopes": scopes, "created_by": p.actor, "created_at": iso(now),
               "project_ids": project_ids, "expires_at": iso(now + timedelta(days=expires_in_days)) if expires_in_days else None,
               "revoked_at": None, "last_used_at": None}
        self.d.db.insert("api_keys", rec, tenant_id=p.tenant_id, ukey=f"prefix:{prefix}")
        audit(self.d, p, "apikey.created", rec["id"], {"name": name, "scopes": scopes})
        return {**sanitize_doc(rec), "token": token}

    def list_api_keys(self, p: Principal) -> list[dict[str, Any]]:
        p.require(Permission.APIKEYS_MANAGE)
        return [sanitize_doc(k) for k in self.d.db.find("api_keys", tenant_id=p.tenant_id, limit=200)]

    def revoke_api_key(self, p: Principal, key_id: str) -> None:
        p.require(Permission.APIKEYS_MANAGE)
        rec = self.d.db.get("api_keys", key_id, tenant_id=p.tenant_id)
        if rec is None:
            raise NotFound("API key not found")
        rec["revoked_at"] = iso(self.d.now())
        self.d.db.put("api_keys", rec, tenant_id=p.tenant_id)
        audit(self.d, p, "apikey.revoked", key_id)

    # ------------------------------------------------------------------ tenant settings
    def update_tenant(self, p: Principal, name: str | None, retention_days: int | None, set_retention: bool,
                      review_sla_hours: int | None = None) -> dict[str, Any]:
        p.require(Permission.PROJECTS_MANAGE)
        t = self.d.db.get("tenants", p.tenant_id, tenant_id=p.tenant_id)
        if t is None:
            raise NotFound("workspace not found")
        if name:
            t["name"] = name
        if set_retention:
            p.require(Permission.RETENTION_MANAGE)
            from ...domain.accounts.plans import F_CONFIG_RETENTION
            self.plans.require_feature(p.tenant_id, F_CONFIG_RETENTION, "Configurable retention")
            plan = self.plans.plan_for(p.tenant_id)
            if retention_days and retention_days > plan.evidence_retention_days:
                raise ValidationFailed(f"retention cannot exceed the plan's {plan.evidence_retention_days} days")
            t["retention_days"] = retention_days
        if review_sla_hours is not None:
            t["settings"] = {**(t.get("settings") or {}), "review_sla_hours": int(review_sla_hours)}
        self.d.db.put("tenants", t, tenant_id=p.tenant_id)
        audit(self.d, p, "tenant.updated", p.tenant_id, {"name": name, "retention_days": retention_days,
                                                         "review_sla_hours": review_sla_hours})
        return sanitize_doc(t)
