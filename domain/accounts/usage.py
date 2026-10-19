"""Usage metering definitions.

Meters are derived from durable stage records, idempotent per (run, meter),
so a retried or replayed stage never charges twice (whitepaper 7.6.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..utils.records import Record

__all__ = ["MIN_BILLABLE_BYTES", "billable_bytes", "METER_RUN", "METER_SCAN_BYTES", "METER_INFERENCE_CENTS",
           "METER_CPU_MS", "UsageEntry", "UsageSummary"]

MIN_BILLABLE_BYTES = 1024          # explicit minimum billable size per run
METER_RUN = "run"
METER_SCAN_BYTES = "scan_bytes"
METER_INFERENCE_CENTS = "inference_cents"
METER_CPU_MS = "cpu_ms"            # internal; recorded to test whether public meters predict cost


def billable_bytes(decoded_bytes: int) -> int:
    return max(int(decoded_bytes), MIN_BILLABLE_BYTES)


@dataclass
class UsageEntry(Record):
    id: str                  # f"{run_id}:{meter}" -> unique, hence idempotent
    tenant_id: str
    period: str
    meter: str
    quantity: int
    recorded_at: datetime
    run_id: str = ""
    project_id: str = ""
    note: str = ""


@dataclass
class UsageSummary:
    period: str
    plan_id: str
    runs: int = 0
    scan_bytes: int = 0
    inference_cents: int = 0
    cpu_ms: int = 0
    limits: dict[str, Any] = field(default_factory=dict)
    projects: int = 0
    seats: int = 0

    def to_dict(self) -> dict[str, Any]:
        def ratio(used: float, cap: float) -> float | None:
            return None if not cap else round(used / cap, 4)
        lim = self.limits
        return {
            "period": self.period, "plan_id": self.plan_id, "runs": self.runs, "scan_bytes": self.scan_bytes,
            "scan_gb": round(self.scan_bytes / 1e9, 6), "inference_cents": self.inference_cents,
            "cpu_ms": self.cpu_ms, "projects": self.projects, "seats": self.seats, "limits": lim,
            "ratios": {"runs": ratio(self.runs, lim.get("runs", 0)),
                       "scan": ratio(self.scan_bytes, lim.get("scan_bytes", 0)),
                       "inference": ratio(self.inference_cents, lim.get("inference_cents", 0)),
                       "projects": ratio(self.projects, lim.get("projects", 0)),
                       "seats": ratio(self.seats, lim.get("seats", 0))},
        }
