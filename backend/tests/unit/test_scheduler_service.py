"""Unit tests for scheduler_service using an in-memory AsyncIOScheduler (no real timers)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.services import scheduler_service


# ---------------------------------------------------------------------------
# Helper: build a stopped scheduler for each test
# ---------------------------------------------------------------------------


def _make_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Test 1: start(poll_minutes=15) adds job with correct trigger and params
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_adds_job_with_interval_15():
    """start(scheduler, 15, sync_fn) adds 'gmail_sync' with IntervalTrigger(minutes=15)."""
    scheduler = _make_scheduler()
    sync_fn = AsyncMock()

    await scheduler_service.start(scheduler, 15, sync_fn)

    job = scheduler.get_job("gmail_sync")
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
    # Verify interval
    trigger = job.trigger
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 15 * 60

    scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Test 2: start(poll_minutes=0) starts scheduler but adds NO job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_poll_minutes_zero_no_job():
    """start(scheduler, 0, sync_fn) starts the scheduler but adds no job."""
    scheduler = _make_scheduler()
    sync_fn = AsyncMock()

    await scheduler_service.start(scheduler, 0, sync_fn)

    job = scheduler.get_job("gmail_sync")
    assert job is None
    assert scheduler.running

    scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Test 3: update_poll_interval(30) reschedules existing job to 30 minutes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_poll_interval_reschedules_existing_job():
    """update_poll_interval(30) when job exists reschedules it to 30 minutes."""
    scheduler = _make_scheduler()
    sync_fn = AsyncMock()
    await scheduler_service.start(scheduler, 15, sync_fn)

    scheduler_service.update_poll_interval(scheduler, 30)

    job = scheduler.get_job("gmail_sync")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 30 * 60

    scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Test 4: update_poll_interval(0) removes the gmail_sync job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_poll_interval_zero_removes_job():
    """update_poll_interval(0) removes the 'gmail_sync' job."""
    scheduler = _make_scheduler()
    sync_fn = AsyncMock()
    await scheduler_service.start(scheduler, 15, sync_fn)

    assert scheduler.get_job("gmail_sync") is not None

    scheduler_service.update_poll_interval(scheduler, 0)

    assert scheduler.get_job("gmail_sync") is None

    scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Test 5: update_poll_interval(10) when no job exists — adds the job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_poll_interval_adds_job_when_absent():
    """update_poll_interval(10) when no job exists adds it."""
    scheduler = _make_scheduler()
    sync_fn = AsyncMock()
    # Start with polling disabled
    await scheduler_service.start(scheduler, 0, sync_fn)
    assert scheduler.get_job("gmail_sync") is None

    scheduler_service.update_poll_interval(scheduler, 10)

    job = scheduler.get_job("gmail_sync")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 10 * 60

    scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Test 6: _scheduled_sync_job swallows exceptions — no re-raise (FR-015)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_sync_job_swallows_exceptions():
    """_scheduled_sync_job catching an exception does NOT re-raise (polling resilience)."""
    # Set a sync_fn that raises
    async def _bad_fn():
        raise RuntimeError("Simulated sync failure")

    scheduler_service._scheduled_sync_fn = _bad_fn

    # Should not raise
    await scheduler_service._scheduled_sync_job()

    # Cleanup
    scheduler_service._scheduled_sync_fn = None
