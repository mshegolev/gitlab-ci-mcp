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
    rate_7d: float
    rate_30d: float
    total_7d: int
    success_7d: int
    failed_7d: int
    total_30d: int
    success_30d: int
    failed_30d: int
    trend: str
    last_10_statuses: list[str] = field(default_factory=list)
    generated_at: str = ""


def _parse_dt(dt_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


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
                get_all=False,
            )
        except Exception as exc:
            logger.warning("Could not load pipelines: %s", exc)
            pipelines = []

        pipelines_7d: list = []
        pipelines_prev_7d: list = []
        pipelines_30d: list = []

        for pl in pipelines:
            dt = _parse_dt(pl.created_at)
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

        sorted_all = sorted(pipelines_30d, key=lambda p: _parse_dt(p.created_at), reverse=True)
        last_10 = [pl.status for pl in sorted_all[:10]]

        return PipelineHealthReport(
            rate_7d=rate_7d,
            rate_30d=rate_30d,
            total_7d=len(pipelines_7d),
            success_7d=success_7d,
            failed_7d=failed_7d,
            total_30d=len(pipelines_30d),
            success_30d=success_30d,
            failed_30d=failed_30d,
            trend=trend,
            last_10_statuses=last_10,
            generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )


def _rate(pipelines: list) -> tuple[float, int, int]:
    if not pipelines:
        return 0.0, 0, 0
    success = sum(1 for p in pipelines if p.status == "success")
    failed = sum(1 for p in pipelines if p.status == "failed")
    total = len(pipelines)
    return (success / total) * 100.0, success, failed


def _trend(current: float, previous: float) -> str:
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "flat"
