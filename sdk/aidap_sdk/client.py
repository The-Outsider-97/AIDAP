"""AIDAP Python SDK - standard library only.

    from aidap_sdk import Client
    c = Client("https://aidap.example.com", api_key="aidk_...")
    result = c.assure("handbook.json", project="prj_...", profile="rag_indexing", metadata={"owner": "HR"})
    if result.release_authorized:
        data = c.artifact(result.run_id)      # only ever succeeds for an authorised PASS
    else:
        print(result.decision, result.reason_codes)
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Client", "AidapError", "Result", "EXIT_CODES"]

EXIT_CODES = {"pass": 0, "review": 10, "quarantine": 20, "block": 30}


class AidapError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None, request_id: str = "") -> None:
        super().__init__(f"[{status} {code}] {message}")
        self.status, self.code, self.message, self.details, self.request_id = status, code, message, details or {}, request_id


@dataclass
class Result:
    run: dict[str, Any]
    decision_detail: dict[str, Any] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        return self.run["id"]

    @property
    def state(self) -> str:
        return self.run.get("state", "")

    @property
    def decision(self) -> str | None:
        return self.run.get("decision")

    @property
    def release_authorized(self) -> bool:
        """True only for an active, unexpired, non-shadow PASS. Anything unclear is False."""
        return bool(self.run.get("release_authorized"))

    @property
    def reason_codes(self) -> list[str]:
        return sorted({r["code"] for r in (self.run.get("decision_detail") or {}).get("reasons", [])})

    @property
    def summary(self) -> str:
        return ((self.run.get("decision_detail") or {}).get("rationale") or {}).get("summary", "")


class Client:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, *, timeout: float = 60.0) -> None:
        self.base = (base_url or os.environ.get("AIDAP_URL") or "http://127.0.0.1:8780").rstrip("/")
        self.key = api_key or os.environ.get("AIDAP_API_KEY") or ""
        self.timeout = timeout
        if not self.key:
            raise ValueError("an API key is required (argument or AIDAP_API_KEY)")

    # ------------------------------------------------------------------ transport
    def _call(self, method: str, path: str, *, body: Any = None, raw: bytes | None = None, headers: dict[str, str] | None = None,
              query: dict[str, Any] | None = None, want_bytes: bool = False) -> Any:
        url = f"{self.base}/api/v1{path}"
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
        h = {"Authorization": f"Bearer {self.key}", "User-Agent": "aidap-sdk/1.0", **(headers or {})}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = r.read()
                return payload if want_bytes else (json.loads(payload) if payload else None)
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read()).get("error", {})
            except Exception:                                          # noqa: BLE001
                err = {}
            raise AidapError(e.code, err.get("code", "http_error"), err.get("message", e.reason), err.get("details"),
                             e.headers.get("X-Request-ID", "")) from None

    # ------------------------------------------------------------------ runs
    def submit(self, data: bytes | str | os.PathLike[str], *, project: str, filename: str = "", profile: str = "", policy: str = "",
               destination: str = "", source_class: str = "unknown", classification: str = "internal", label: str = "",
               metadata: dict[str, Any] | None = None, idempotency_key: str = "", asset_name: str = "") -> dict[str, Any]:
        """Submit an artifact for assurance. Returns the queued run; use ``wait`` or ``assure`` for the decision."""
        if isinstance(data, (str, os.PathLike)) and os.path.exists(str(data)):
            filename = filename or os.path.basename(str(data))
            with open(str(data), "rb") as fh:
                payload = fh.read()
        elif isinstance(data, str):
            payload = data.encode("utf-8")
        else:
            payload = bytes(data)
        q = {"project_id": project, "profile_id": profile, "policy_id": policy, "destination_id": destination,
             "source_class": source_class, "classification": classification, "label": label, "asset_name": asset_name}
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        h = {"Content-Type": "application/octet-stream", "X-Filename": filename or "upload", "X-Media-Type": ctype,
             "Idempotency-Key": idempotency_key or uuid.uuid4().hex}
        if metadata:
            q["metadata"] = json.dumps(metadata)
        return self._call("POST", "/runs", raw=payload, headers=h, query=q)

    def run(self, run_id: str) -> dict[str, Any]:
        return self._call("GET", f"/runs/{run_id}")

    def wait(self, run_id: str, *, timeout: float = 300.0, interval: float = 1.0) -> Result:
        deadline = time.monotonic() + timeout
        while True:
            run = self.run(run_id)
            if run["state"] in ("completed", "failed", "cancelled"):
                return Result(run)
            if time.monotonic() > deadline:
                raise TimeoutError(f"run {run_id} did not finish within {timeout:.0f}s (state: {run['state']})")
            time.sleep(interval)

    def assure(self, data: Any, *, wait_timeout: float = 300.0, **kw: Any) -> Result:
        """Submit and wait for the decision."""
        run = self.submit(data, **kw)
        return self.wait(run["id"], timeout=wait_timeout)

    def runs(self, **filters: Any) -> dict[str, Any]:
        return self._call("GET", "/runs", query=filters)

    def findings(self, run_id: str, **filters: Any) -> dict[str, Any]:
        return self._call("GET", f"/runs/{run_id}/findings", query=filters)

    def evidence(self, run_id: str) -> dict[str, Any]:
        return self._call("GET", f"/runs/{run_id}/evidence")

    def report(self, run_id: str, fmt: str = "json") -> bytes:
        return self._call("GET", f"/runs/{run_id}/report", query={"format": fmt, "download": "1"}, want_bytes=True)

    def artifact(self, run_id: str) -> bytes:
        """The assured artifact. Raises ``AidapError(403, 'release_not_authorized')`` unless the decision authorises release."""
        return self._call("GET", f"/runs/{run_id}/artifact", want_bytes=True)

    def simulate(self, content: str, *, profile: str = "", profile_document: dict | None = None, policy: str = "",
                 policy_document: dict | None = None, filename: str = "sample.txt", **kw: Any) -> dict[str, Any]:
        body: dict[str, Any] = {"content": content, "filename": filename, **kw}
        if profile:
            body["profile_id"] = profile
        if profile_document:
            body["profile"] = profile_document
        if policy:
            body["policy_id"] = policy
        if policy_document:
            body["policy"] = policy_document
        return self._call("POST", "/simulate", body=body)

    def usage(self) -> dict[str, Any]:
        return self._call("GET", "/usage")

    # ------------------------------------------------------------------ insights, feedback and test suites
    def insights(self, days: int = 30, project: str = "") -> dict[str, Any]:
        return self._call("GET", "/insights", query={"days": days, "project_id": project})

    def metrics(self, days: int = 30) -> str:
        """Prometheus text exposition of the workspace's operating metrics (Team plan and above)."""
        return self._call("GET", "/insights/metrics", query={"days": days}, want_bytes=True).decode("utf-8")

    def rate_finding(self, run_id: str, finding_id: str, verdict: str, note: str = "") -> dict[str, Any]:
        """verdict: useful | false_positive | unclear. Feedback informs policy owners; it never changes a decision."""
        return self._call("POST", f"/runs/{run_id}/findings/{finding_id}/feedback", body={"verdict": verdict, "note": note})

    def suites(self) -> list[dict[str, Any]]:
        return self._call("GET", "/suites")

    def run_suite(self, suite_id: str, *, profile: str = "", policy: str = "", profile_document: dict | None = None,
                  policy_document: dict | None = None) -> dict[str, Any]:
        """Evaluate a golden-set suite with deterministic checks. Nothing is stored as a run and no quota is used."""
        body: dict[str, Any] = {}
        if profile:
            body["profile_id"] = profile
        if policy:
            body["policy_id"] = policy
        if profile_document:
            body["profile"] = profile_document
        if policy_document:
            body["policy"] = policy_document
        return self._call("POST", f"/suites/{suite_id}/run", body=body)

    def suggest_profile(self, data: bytes | str | os.PathLike[str], *, filename: str = "", name: str = "") -> dict[str, Any]:
        """Draft an intended-use profile from a representative sample. Nothing is stored."""
        if isinstance(data, (str, os.PathLike)) and os.path.exists(str(data)):
            filename = filename or os.path.basename(str(data))
            with open(str(data), "rb") as fh:
                payload = fh.read()
        else:
            payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        return self._call("POST", "/profiles/suggest", raw=payload, query={"name": name},
                          headers={"Content-Type": "application/octet-stream", "X-Filename": filename or "sample.csv"})

    def projects(self) -> list[dict[str, Any]]:
        return self._call("GET", "/projects")
