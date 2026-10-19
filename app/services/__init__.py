"""Service composition. ``build_services`` is the only place services are wired together."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...domain.utils.domain_errors import AIDAPError
from ..deps import Deps
from .auth import AuthService
from .catalog import ConfigService
from .delivery import DeliveryRetry, DeliveryService
from .insights import AssetQueries, InsightsService
from .notify import NotificationService
from .ops import BillingService, ContactService, DashboardQueries, RetentionService, ScheduleRunner
from .plans import PlanService, UsageService
from .review import QuarantineService, ReviewService
from .runs import RunService
from .simulate import SimulationService
from .suites import SuggestionService, SuiteService
from .workspace import (AlertService, AuditQueries, BaselineService, DestinationService, ProjectService,
                        ScheduleService)

__all__ = ["Services", "build_services", "JOB_KINDS"]

JOB_KINDS = ["run", "delivery", "outbox"]


@dataclass
class Services:
    deps: Deps
    plans: PlanService
    usage: UsageService
    notify: NotificationService
    auth: AuthService
    configs: ConfigService
    projects: ProjectService
    destinations: DestinationService
    baselines: BaselineService
    alerts: AlertService
    audit: AuditQueries
    schedules: ScheduleService
    delivery: DeliveryService
    runs: RunService
    reviews: ReviewService
    quarantine: QuarantineService
    billing: BillingService
    scheduler: ScheduleRunner
    retention: RetentionService
    contact: ContactService
    dashboard: DashboardQueries
    simulation: SimulationService
    insights: InsightsService
    assets: AssetQueries
    suites: SuiteService
    suggestions: SuggestionService

    # ------------------------------------------------------------------ background work
    def process_job(self, job: Any) -> str:
        """Run one leased job. Returns "done"; raises to request a retry (the queue applies backoff and dead-lettering)."""
        kind, payload = job.kind, job.payload
        if kind == "run":
            state = self.runs.execute(payload["run_id"])
            return state
        if kind == "delivery":
            return self.delivery.process(payload["delivery_id"])
        if kind == "outbox":
            return self.notify.process(payload["id"])
        raise AIDAPError(f"unknown job kind {kind!r}")

    def run_one(self, worker: str = "inline") -> bool:
        """Lease and process a single job. Returns False when there is nothing to do."""
        job = self.deps.queue.lease(JOB_KINDS, worker, self.deps.settings.lease_seconds)
        if job is None:
            return False
        try:
            self.process_job(job)
        except DeliveryRetry as exc:
            self.deps.queue.fail(job.id, str(exc)[:300], retry_in_seconds=min(30 * (2 ** (job.attempts - 1)), 900))
        except Exception as exc:                                        # noqa: BLE001
            self.deps.queue.fail(job.id, f"{type(exc).__name__}: {str(exc)[:300]}",
                                 retry_in_seconds=min(5 * (2 ** (job.attempts - 1)), 300))
        else:
            self.deps.queue.complete(job.id)
        return True

    def drain(self, limit: int = 1000) -> int:
        n = 0
        while n < limit and self.run_one():
            n += 1
        return n

    def housekeeping(self) -> dict[str, int]:
        """Periodic duties: due schedules, outbox sweep, exception expiry, retention, quarantine retention."""
        return {"schedules": self.scheduler.tick(), "outbox": self.notify.sweep(),
                "exceptions": self.reviews.sweep_expired(), "quarantine": self.quarantine.sweep(),
                "retention": self.retention.sweep(), "review_sla": self.insights.sweep_overdue()}


def build_services(deps: Deps) -> Services:
    plans = PlanService(deps)
    usage = UsageService(deps, plans)
    notify = NotificationService(deps)
    configs = ConfigService(deps, plans)
    deps.configs = configs
    alerts = AlertService(deps)
    baselines = BaselineService(deps, plans)
    delivery = DeliveryService(deps, plans, alerts)
    runs = RunService(deps, plans, usage, baselines, alerts, notify, delivery)
    simulation = SimulationService(deps, plans)
    return Services(
        deps=deps, plans=plans, usage=usage, notify=notify, auth=AuthService(deps, plans, notify), configs=configs,
        projects=ProjectService(deps, plans), destinations=DestinationService(deps, plans), baselines=baselines,
        alerts=alerts, audit=AuditQueries(deps, plans), schedules=ScheduleService(deps, plans), delivery=delivery,
        runs=runs, reviews=ReviewService(deps, plans, runs), quarantine=QuarantineService(deps),
        billing=BillingService(deps, plans, notify, alerts), scheduler=ScheduleRunner(deps, plans, runs, alerts),
        retention=RetentionService(deps, plans), contact=ContactService(deps, notify), dashboard=DashboardQueries(deps, usage),
        simulation=simulation, insights=InsightsService(deps, plans, alerts), assets=AssetQueries(deps),
        suites=SuiteService(deps, plans, simulation), suggestions=SuggestionService(deps, plans))
