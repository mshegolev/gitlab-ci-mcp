"""Pipeline health report — success rate over 7/30 days, trend, last 10 statuses."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gitlab_ci_mcp.ci_manager import GitLabCIManager

logger = logging.getLogger(__name__)


@dataclass
class PipelineHealthReport:
    rate_7d: float | None
    rate_30d: float | None
    total_7d: int
    completed_7d: int
    success_7d: int
    failed_7d: int
    total_30d: int
    completed_30d: int
    success_30d: int
    failed_30d: int
    trend: str
    last_10_statuses: list[str] = field(default_factory=list)
    generated_at: str = ""
    status: str = "ok"
    invalid_timestamps: int = 0
    insufficient_data: bool = False
    rate_basis: str = "completed pipelines only: success and failed"


def _parse_dt(dt_str: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


class PipelineHealthCollector:
    def __init__(self, ci_manager: GitLabCIManager) -> None:
        self.ci = ci_manager

    def collect(self, ref: str = "master", source: str = "schedule") -> PipelineHealthReport:
        now = datetime.now(timezone.utc)
        cutoff_30d = now - timedelta(days=30)
        cutoff_7d = now - timedelta(days=7)
        cutoff_14d = now - timedelta(days=14)

        try:
            pipelines = self.ci.project.pipelines.list(
                ref=ref,
                source=source,
                updated_after=cutoff_30d.isoformat(),
                per_page=100,
                get_all=True,
            )
        except Exception as exc:
            logger.warning("Could not load pipelines: %s", exc)
            raise RuntimeError(f"pipeline health API request failed: {exc}") from exc

        pipelines_7d: list = []
        pipelines_prev_7d: list = []
        pipelines_30d: list = []

        invalid_timestamps = 0
        for pl in pipelines:
            dt = _parse_dt(pl.created_at)
            if dt is None:
                invalid_timestamps += 1
                continue
            if dt >= cutoff_30d:
                pipelines_30d.append(pl)
            if dt >= cutoff_7d:
                pipelines_7d.append(pl)
            elif dt >= cutoff_14d:
                pipelines_prev_7d.append(pl)

        rate_7d, success_7d, failed_7d = _rate(pipelines_7d)
        rate_30d, success_30d, failed_30d = _rate(pipelines_30d)
        rate_prev_7d, _, _ = _rate(pipelines_prev_7d)

        trend = _trend(rate_7d, rate_prev_7d)

        sorted_all = sorted(
            pipelines_30d,
            key=lambda p: _parse_dt(p.created_at) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        last_10 = [pl.status for pl in sorted_all[:10]]
        insufficient = rate_7d is None or rate_30d is None or rate_prev_7d is None
        status = "no_data" if not pipelines_30d else ("insufficient_data" if insufficient else "ok")

        return PipelineHealthReport(
            rate_7d=rate_7d,
            rate_30d=rate_30d,
            total_7d=len(pipelines_7d),
            completed_7d=success_7d + failed_7d,
            success_7d=success_7d,
            failed_7d=failed_7d,
            total_30d=len(pipelines_30d),
            completed_30d=success_30d + failed_30d,
            success_30d=success_30d,
            failed_30d=failed_30d,
            trend=trend,
            last_10_statuses=last_10,
            generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            status=status,
            invalid_timestamps=invalid_timestamps,
            insufficient_data=insufficient,
        )


def _rate(pipelines: list) -> tuple[float | None, int, int]:
    success = sum(1 for p in pipelines if p.status == "success")
    failed = sum(1 for p in pipelines if p.status == "failed")
    total = success + failed
    if not total:
        return None, 0, 0
    return (success / total) * 100.0, success, failed


def _trend(current: float | None, previous: float | None) -> str:
    if current is None or previous is None:
        return "insufficient_data"
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "flat"
