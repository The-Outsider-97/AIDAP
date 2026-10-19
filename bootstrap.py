"""Composition root: the one place where configuration, adapters and services meet.

Configuration = ``configs/main.yaml`` overlaid by ``AIDAP_*`` environment variables. Secrets are read only from the
environment (or, in development, generated once into the data directory with owner-only permissions).
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any, Mapping

import yaml

from .app.deps import Deps, Settings
from .app.services import Services, build_services
from .app.services.catalog import TemplateCatalog, load_plans
from .domain.utils.domain_errors import Unavailable

__all__ = ["bootstrap", "load_config", "build_settings", "CONFIG_DIR"]

CONFIG_DIR = Path(__file__).resolve().parent / "configs"

_TRUE = {"1", "true", "yes", "on"}


def _b(v: Any) -> bool:
    return str(v).strip().lower() in _TRUE


def load_config(path: str | os.PathLike[str] | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    path = path or env.get("AIDAP_CONFIG") or (CONFIG_DIR / "main.yaml")
    cfg: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for sect in ("app", "server", "data", "workers", "limits", "security", "billing", "slai"):
        cfg.setdefault(sect, {})
    return cfg


def build_settings(cfg: dict[str, Any], env: Mapping[str, str], data_dir: str | None = None) -> Settings:
    a, w, lim, sec, bil, sl = (cfg[k] for k in ("app", "workers", "limits", "security", "billing", "slai"))

    def pick(name: str, default: Any) -> Any:
        return env.get(name, default)
    environment = str(pick("AIDAP_ENV", a.get("environment", "development"))).lower()
    prod = environment == "production"
    st = Settings(
        environment=environment, base_url=str(pick("AIDAP_BASE_URL", a.get("base_url", "http://127.0.0.1:8780"))).rstrip("/"),
        business_email=str(pick("AIDAP_BUSINESS_EMAIL", a.get("business_email", "info.remy3design@gmail.com"))),
        data_dir=str(data_dir or pick("AIDAP_DATA_DIR", cfg["data"].get("dir", "./var"))),
        inline_workers=_b(pick("AIDAP_INLINE_WORKERS", w.get("inline", True))),
        poll_seconds=float(w.get("poll_seconds", 1.0)), lease_seconds=int(w.get("lease_seconds", 300)),
        max_attempts=int(w.get("max_attempts", 3)), max_upload_bytes=int(lim.get("max_upload_bytes", 104857600)),
        max_text_chars=int(lim.get("max_text_chars", 5_000_000)), parse_timeout=int(lim.get("parse_timeout_seconds", 20)),
        request_rate_per_minute=int(pick("AIDAP_RATE_PER_MINUTE", lim.get("request_rate_per_minute", 240))),
        login_rate_per_minute=int(lim.get("login_rate_per_minute", 10)), session_hours=int(sec.get("session_hours", 12)),
        csrf=bool(sec.get("csrf", True)), password_min_length=int(sec.get("password_min_length", 12)),
        mfa_issuer=str(sec.get("mfa_issuer", "AIDAP")), billing_provider=str(pick("AIDAP_BILLING_PROVIDER", bil.get("provider", "sandbox"))).lower(),
        auto_overage=_b(bil.get("auto_overage", False)),
        allow_http_targets=_b(pick("AIDAP_ALLOW_HTTP_TARGETS", False)), allow_private_targets=_b(pick("AIDAP_ALLOW_PRIVATE_TARGETS", False)),
        cookie_secure=_b(pick("AIDAP_COOKIE_SECURE", prod)), slai_enabled=_b(pick("AIDAP_SLAI_ENABLED", sl.get("enabled", True))))
    if prod:
        problems = []
        if st.allow_http_targets or st.allow_private_targets:
            problems.append("AIDAP_ALLOW_HTTP_TARGETS / AIDAP_ALLOW_PRIVATE_TARGETS must not be set in production")
        if not st.base_url.startswith("https://"):
            problems.append("AIDAP_BASE_URL must be https:// in production")
        if not st.cookie_secure:
            problems.append("AIDAP_COOKIE_SECURE must be true in production")
        if st.billing_provider == "sandbox":
            problems.append("billing provider 'sandbox' is not allowed in production (use 'stripe' or 'none')")
        if not env.get("AIDAP_SECRET_KEYS") or not env.get("AIDAP_PEPPER"):
            problems.append("AIDAP_SECRET_KEYS and AIDAP_PEPPER are required in production")
        if problems:
            raise Unavailable("unsafe production configuration: " + "; ".join(problems), code="config_error")
    return st


def _pepper(env: Mapping[str, str], data: Path, production: bool) -> str:
    if env.get("AIDAP_PEPPER"):
        return env["AIDAP_PEPPER"]
    f = data / "secrets" / "pepper"
    if f.exists():
        return f.read_text().strip()
    if production:
        raise Unavailable("AIDAP_PEPPER is required in production", code="config_error")
    f.parent.mkdir(parents=True, exist_ok=True)
    val = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(val)
    return val


def bootstrap(config_path: str | None = None, env: Mapping[str, str] | None = None, *, data_dir: str | None = None,
              overrides: dict[str, Any] | None = None, deps_overrides: dict[str, Any] | None = None) -> Services:
    """Build every adapter and service. ``deps_overrides`` lets tests substitute fakes for individual ports."""
    from .slai.runtime import ensure_path
    ensure_path()
    from .infra.billing.sandbox import NoBilling, SandboxBilling
    from .infra.billing.stripe_rest import StripeBilling
    from .infra.crypto.passwords import SlaiPasswordService
    from .infra.crypto.secretbox import AesGcmSecretBox, load_keys
    from .infra.crypto.tokens import HmacTokenService
    from .infra.crypto.totp import Rfc6238Totp
    from .infra.malware.scanner import ClamdScanner, CompositeScanner
    from .infra.net.safe_fetch import PinnedSafeFetcher
    from .infra.notifications.mailer import build_mailer
    from .infra.notifications.webhooks import SlaiWebhookSender
    from .infra.persistence.sqlite_store import SqliteDocStore
    from .infra.queue.sqlite_queue import SqliteJobQueue
    from .infra.ratelimit.limiter import SlaiRateLimiter
    from .infra.storage.blobstore import SlaiBlobStore, SlaiObjectDelivery
    from .slai.orchestration import build_slai_runtime

    env = os.environ if env is None else env
    cfg = load_config(config_path, env)
    for k, v in (overrides or {}).items():
        cfg.setdefault(k, {}).update(v)
    st = build_settings(cfg, env, data_dir)
    data = Path(st.data_dir).resolve()
    data.mkdir(parents=True, exist_ok=True)
    keys = load_keys(env.get("AIDAP_SECRET_KEYS"), data / "secrets" / "master.key", allow_generate=not st.production)
    box = AesGcmSecretBox(keys)
    pepper = _pepper(env, data, st.production)
    db = SqliteDocStore(data / "aidap.sqlite3")
    queue = SqliteJobQueue(db)
    blobs = SlaiBlobStore(str(data / "blobs"), box)
    objects = SlaiObjectDelivery(str(data / "delivered"))
    smtp = ({"host": env["AIDAP_SMTP_HOST"], "port": env.get("AIDAP_SMTP_PORT", "587"), "user": env.get("AIDAP_SMTP_USER", ""),
             "password": env.get("AIDAP_SMTP_PASSWORD", ""), "tls": _b(env.get("AIDAP_SMTP_TLS", "true")),
             "ssl": _b(env.get("AIDAP_SMTP_SSL", "false"))} if env.get("AIDAP_SMTP_HOST") else None)
    mailer = build_mailer(mailbox_dir=data / "mailbox", default_from=env.get("AIDAP_MAIL_FROM", st.business_email), smtp=smtp)
    if st.billing_provider == "stripe":
        prices = {pid: env.get(f"AIDAP_STRIPE_PRICE_{pid.upper()}", "") for pid in ("starter", "team", "business")}
        billing: Any = StripeBilling(env.get("AIDAP_STRIPE_SECRET_KEY", ""), env.get("AIDAP_STRIPE_WEBHOOK_SECRET", ""), prices)
    elif st.billing_provider == "none":
        billing = NoBilling()
    else:
        billing = SandboxBilling(st.base_url)
    clamd = None
    if env.get("AIDAP_CLAMD_HOST") or env.get("AIDAP_CLAMD_SOCKET"):
        clamd = ClamdScanner(host=env.get("AIDAP_CLAMD_HOST", "127.0.0.1"), port=int(env.get("AIDAP_CLAMD_PORT", "3310")),
                             unix_socket=env.get("AIDAP_CLAMD_SOCKET", ""))
    slai = build_slai_runtime(checkpoint_dir=str(data / "checkpoints"),
                              docstore=db, enabled=st.slai_enabled)
    plans = load_plans(CONFIG_DIR)
    parts: dict[str, Any] = dict(
        settings=st, db=db, blobs=blobs, queue=queue, passwords=SlaiPasswordService(pepper, st.password_min_length), box=box,
        tokens=HmacTokenService(pepper), totp=Rfc6238Totp(), scanner=CompositeScanner(clamd), mailer=mailer,
        webhooks=SlaiWebhookSender(allow_http=st.allow_http_targets, allow_private_hosts=st.allow_private_targets),
        billing=billing, limiter=SlaiRateLimiter(st.request_rate_per_minute), login_limiter=SlaiRateLimiter(st.login_rate_per_minute),
        checkpoints=slai.checkpoints, fetcher=PinnedSafeFetcher(allow_http=st.allow_http_targets, allow_private_hosts=st.allow_private_targets),
        objects=objects, plans=plans, catalog=TemplateCatalog(CONFIG_DIR), slai=slai)
    parts.update(deps_overrides or {})
    return build_services(Deps(**parts))
