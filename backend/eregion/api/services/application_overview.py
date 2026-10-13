"""Pipeline and weekly activity figures for the Applications page."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from eregion.runtime.workspace.types import ApplicationStatus as S

FUNNEL = ("saved", "analyzed", "applied", "interviewing", "offer")
_BEFORE_ANALYSIS = {S.SAVED, S.ANALYZING, S.ANALYSIS_FAILED}
_APPLIED = {S.APPLIED, S.INTERVIEWING, S.OFFER}
_RESPONDED = {S.INTERVIEWING, S.OFFER, S.REJECTED}


def stage_reached(status: S, *, match_score: float | None, applied_at: datetime | None) -> int:
    """Furthest funnel stage an application has reached, as an index into ``FUNNEL``."""
    if status == S.OFFER:
        return 4
    if status == S.INTERVIEWING:
        return 3
    if applied_at is not None or status in _APPLIED:
        return 2
    if match_score is not None or status not in _BEFORE_ANALYSIS:
        return 1
    return 0


def week_start(moment: date) -> date:
    return moment - timedelta(days=moment.weekday())


def overview(applications, *, weeks: int = 10, today: date | None = None) -> dict:
    """``applications`` are summaries with ``status``, ``match_score`` and ``applied_at``.

    Archived applications are left out of the figures; withdrawn and rejected ones still
    count toward the stages they reached before closing.
    """
    tracked = [a for a in applications if S(a.status) != S.ARCHIVED]
    reached = [stage_reached(S(a.status), match_score=a.match_score, applied_at=a.applied_at) for a in tracked]
    funnel = [{"stage": name, "count": sum(r >= index for r in reached)} for index, name in enumerate(FUNNEL)]

    first = week_start(today or datetime.now(UTC).date()) - timedelta(weeks=weeks - 1)
    weekly = [{"week_start": first + timedelta(weeks=i), "count": 0} for i in range(weeks)]
    for item in tracked:
        if item.applied_at is None:
            continue
        index = (week_start(item.applied_at.astimezone(UTC).date()) - first).days // 7
        if 0 <= index < weeks:
            weekly[index]["count"] += 1

    applied = [a for a, r in zip(tracked, reached) if r >= 2]
    responded = sum(S(a.status) in _RESPONDED for a in applied)
    return {
        "funnel": funnel,
        "weekly": weekly,
        "totals": {
            "tracked": len(tracked),
            "applied": len(applied),
            "interviewing": sum(S(a.status) == S.INTERVIEWING for a in tracked),
            "offers": sum(S(a.status) == S.OFFER for a in tracked),
            "rejected": sum(S(a.status) == S.REJECTED for a in tracked),
            "response_rate": round(100 * responded / len(applied)) if applied else None,
        },
    }
