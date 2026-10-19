"""Request contracts for every mutating endpoint (validated before any service runs)."""

from __future__ import annotations

from ..domain.data.classification import DataClassification, DestinationClass, DeliveryKind, SourceClass
from ..domain.governance.authorization import SCOPE_PERMISSIONS, Role
from .validation import b, email, enum, free, i, lst, obj, s, ts, url

__all__ = ["SIGNUP", "LOGIN", "PASSWORD_CHANGE", "PASSWORD_RESET_REQUEST", "PASSWORD_RESET_CONFIRM",
           "MFA_CODE", "MFA_DISABLE", "INVITE_CREATE", "INVITE_ACCEPT", "MEMBER_UPDATE", "TENANT_UPDATE",
           "API_KEY_CREATE", "PROJECT_CREATE", "PROJECT_UPDATE", "CONFIG_CREATE", "CONFIG_VERSION",
           "LINT", "DESTINATION_CREATE", "DESTINATION_UPDATE", "BASELINE_PROPOSE", "RUN_SUBMIT", "RUN_JSON",
           "REVIEW_RESOLVE", "REVIEW_ASSIGN", "QUARANTINE_ACCESS", "QUARANTINE_DISPOSE", "CHECKOUT", "TOPUP",
           "BILLING_SETTINGS", "SCHEDULE_CREATE", "SCHEDULE_UPDATE", "CONTACT", "REDACT", "SIMULATE_FIELDS",
           "RUN_FIELDS_MULTIPART", "ALERT_ACK", "FINDING_FEEDBACK", "SUITE_CREATE", "SUITE_CASE", "SUITE_RUN",
           "PUBLISH_GATE", "SUGGEST_FIELDS"]

_SLUG = r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}"

SIGNUP = {"email": email(), "name": s(120, min=1, required=True), "password": s(256, min=1, required=True, strip=False),
          "organization": s(120, min=2, required=True), "accept_terms": b(required=True)}
LOGIN = {"email": email(), "password": s(256, required=True, strip=False), "code": s(20, default="")}
PASSWORD_CHANGE = {"current_password": s(256, required=True, strip=False),
                   "new_password": s(256, min=1, required=True, strip=False)}
PASSWORD_RESET_REQUEST = {"email": email()}
PASSWORD_RESET_CONFIRM = {"token": s(200, required=True), "new_password": s(256, min=1, required=True, strip=False)}
MFA_CODE = {"code": s(20, min=6, required=True)}
MFA_DISABLE = {"code": s(20, min=6, required=True), "password": s(256, required=True, strip=False)}

_ROLES = [r.value for r in Role if r != Role.OWNER]
INVITE_CREATE = {"email": email(), "role": enum(_ROLES, required=True), "project_ids": lst(s(80), max=50)}
INVITE_ACCEPT = {"token": s(200, required=True), "name": s(120, default=""), "password": s(256, default="", strip=False)}
MEMBER_UPDATE = {"role": enum(_ROLES, required=True), "project_ids": lst(s(80), max=50)}
TENANT_UPDATE = {"name": s(120, min=2), "retention_days": i(1, 3650, nullable=True), "review_sla_hours": i(1, 720)}
API_KEY_CREATE = {"name": s(80, min=1, required=True),
                  "scopes": lst(enum(list(SCOPE_PERMISSIONS)), min=1, max=10, required=True),
                  "project_ids": lst(s(80), max=50), "expires_in_days": i(1, 730, nullable=True)}

PROJECT_CREATE = {"name": s(100, min=2, required=True), "description": s(500),
                  "default_profile_id": s(80), "default_policy_id": s(80, default="standard"),
                  "default_destination_id": s(80)}
PROJECT_UPDATE = {"name": s(100, min=2), "description": s(500), "default_profile_id": s(80),
                  "default_policy_id": s(80), "default_destination_id": s(80), "archived": b()}

CONFIG_CREATE = {"id": s(64, min=2, required=True, pattern=_SLUG), "name": s(120, min=2, required=True),
                 "document": free(required=True), "note": s(300)}
CONFIG_VERSION = {"document": free(required=True), "note": s(300)}
LINT = {"profile": free(), "policy": free()}

DESTINATION_CREATE = {"name": s(100, min=2, required=True),
                      "klass": enum([d.value for d in DestinationClass], required=True),
                      "delivery": enum([d.value for d in DeliveryKind], default="pull"),
                      "target_url": url(), "secret": s(256, strip=False), "description": s(300),
                      "project_id": s(80, default="")}
DESTINATION_UPDATE = {"name": s(100, min=2), "klass": enum([d.value for d in DestinationClass]),
                      "delivery": enum([d.value for d in DeliveryKind]), "target_url": url(),
                      "secret": s(256, strip=False), "description": s(300), "enabled": b()}

BASELINE_PROPOSE = {"run_id": s(80, required=True), "name": s(120, default="")}

_SOURCE = [c.value for c in SourceClass]
_CLASSIF = [c.value for c in DataClassification]
RUN_FIELDS_MULTIPART = {"project_id": s(80, required=True), "profile_id": s(80, default=""),
                        "policy_id": s(80, default=""), "destination_id": s(80, default=""),
                        "source_class": enum(_SOURCE, default="unknown"),
                        "classification": enum(_CLASSIF, default="internal"),
                        "label": s(120), "idempotency_key": s(120), "asset_name": s(200),
                        "metadata": free(), "wait": b()}
RUN_JSON = {**RUN_FIELDS_MULTIPART, "content": s(5_000_000, strip=False), "filename": s(200, default="input.txt"),
            "media_type": s(120)}
RUN_SUBMIT = RUN_JSON
SIMULATE_FIELDS = {"profile": free(), "profile_id": s(80), "policy": free(), "policy_id": s(80),
                   "destination": enum([d.value for d in DestinationClass], default="local_index"),
                   "source_class": enum(_SOURCE, default="unknown"),
                   "classification": enum(_CLASSIF, default="internal"), "metadata": free(),
                   "content": s(5_000_000, strip=False), "filename": s(200, default="sample.txt")}
REDACT = {"note": s(300)}

REVIEW_RESOLVE = {"resolution": enum(["approve_exception", "reject", "request_repair"], required=True),
                  "comment": s(2000), "reason_codes": lst(s(120), max=50), "days": i(1, 365, nullable=True)}
REVIEW_ASSIGN = {"assignee": s(80, required=True)}
QUARANTINE_ACCESS = {"purpose": s(500, min=5, required=True)}
QUARANTINE_DISPOSE = {"action": enum(["delete", "release_for_investigation"], required=True),
                      "comment": s(500, min=3, required=True)}
ALERT_ACK = {"note": s(300)}

CHECKOUT = {"plan_id": enum(["developer", "starter", "team", "business"], required=True)}
TOPUP = {"amount_cents": i(500, 100_000, required=True)}
BILLING_SETTINGS = {"auto_overage": b(), "hold_on_exhaustion": b()}

SCHEDULE_CREATE = {"project_id": s(80, required=True), "name": s(100, min=2, required=True),
                   "interval_minutes": i(15, 10080, required=True), "source_url": url(required=True),
                   "profile_id": s(80, required=True), "policy_id": s(80, default=""), "destination_id": s(80)}
SCHEDULE_UPDATE = {"name": s(100, min=2), "interval_minutes": i(15, 10080), "source_url": url(),
                   "profile_id": s(80), "policy_id": s(80), "destination_id": s(80), "enabled": b()}

CONTACT = {"name": s(120, min=1, required=True), "email": email(), "company": s(160),
           "topic": enum(["enterprise", "sales", "support", "security", "other"], default="enterprise"),
           "message": s(4000, min=10, required=True), "website": s(200)}   # `website` is a honeypot

FINDING_FEEDBACK = {"verdict": enum(["useful", "false_positive", "unclear"], required=True), "note": s(300)}
SUITE_CREATE = {"name": s(100, min=2, required=True), "description": s(500), "project_id": s(80)}
SUITE_CASE = {"name": s(100), "expected": enum(["pass", "review", "quarantine", "block"], required=True),
              "expected_codes": lst(s(120), max=20), "destination": enum([d.value for d in DestinationClass], default="local_index"),
              "source_class": enum(_SOURCE, default="unknown"), "classification": enum(_CLASSIF, default="internal"),
              "metadata": free(), "note": s(300), "content": s(200_000, strip=False), "filename": s(200, default="sample.txt")}
SUITE_RUN = {"profile": free(), "profile_id": s(80), "policy": free(), "policy_id": s(80)}
PUBLISH_GATE = {"suite_ids": lst(s(80), max=5), "profile_id": s(80), "policy_id": s(80)}
SUGGEST_FIELDS = {"name": s(100), "task": s(80), "content": s(5_000_000, strip=False), "filename": s(200, default="sample.csv")}
