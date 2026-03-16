"""Scheduler service — APScheduler 3.x AsyncIOScheduler for automatic mail polling (US3).

Uses AsyncIOScheduler (not BackgroundScheduler) as specified in research.md §8.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.logging_config import get_logger

logger = get_logger(__name__)

# Module-level reference to the bound sync coroutine (set at startup)
_scheduled_sync_fn: Callable | None = None

_JOB_ID = "gmail_sync"


async def _scheduled_sync_job() -> None:
    """Scheduled job that calls the bound sync function.

    Catches ALL exceptions and logs them — never re-raises so that APScheduler
    continues polling on the next interval (FR-015).
    """
    if _scheduled_sync_fn is None:
        logger.warning("scheduler_sync_fn_not_set")
        return
    try:
        await _scheduled_sync_fn()
    except Exception as exc:  # noqa: BLE001
        logger.error("scheduler_sync_failed", error=str(exc), exc_info=True)


async def start(
    scheduler: AsyncIOScheduler,
    poll_minutes: int,
    sync_fn: Callable,
) -> None:
    """Start the scheduler and optionally add the polling job.

    Args:
        scheduler: An AsyncIOScheduler instance (created in lifespan).
        poll_minutes: Polling interval in minutes. 0 = no job added (polling disabled).
        sync_fn: Bound coroutine to call on each scheduled tick.
    """
    global _scheduled_sync_fn
    _scheduled_sync_fn = sync_fn

    scheduler.start()
    logger.info("scheduler_started")

    if poll_minutes > 0:
        scheduler.add_job(
            _scheduled_sync_job,
            IntervalTrigger(minutes=poll_minutes),
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("scheduler_job_added", poll_minutes=poll_minutes)
    else:
        logger.info("scheduler_polling_disabled")


def update_poll_interval(scheduler: AsyncIOScheduler, minutes: int) -> None:
    """Reconfigure the polling interval at runtime (FR-014).

    - minutes == 0 and job exists → remove job (disable polling)
    - minutes > 0 and job exists → reschedule with new interval
    - minutes > 0 and job absent → add job
    """
    job = scheduler.get_job(_JOB_ID)

    if minutes == 0:
        if job is not None:
            scheduler.remove_job(_JOB_ID)
            logger.info("scheduler_job_removed")
        else:
            logger.info("scheduler_polling_already_disabled")
    else:
        if job is not None:
            scheduler.reschedule_job(
                _JOB_ID,
                trigger=IntervalTrigger(minutes=minutes),
            )
            logger.info("scheduler_job_rescheduled", poll_minutes=minutes)
        else:
            scheduler.add_job(
                _scheduled_sync_job,
                IntervalTrigger(minutes=minutes),
                id=_JOB_ID,
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            logger.info("scheduler_job_added", poll_minutes=minutes)


async def shutdown(scheduler: AsyncIOScheduler) -> None:
    """Gracefully stop the scheduler (called during lifespan teardown)."""
    scheduler.shutdown(wait=False)
    logger.info("scheduler_stopped")
