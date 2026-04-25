#!/usr/bin/env python3
import logging
import signal
import sys
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

import db
import espn
import scheduler as sched
from config import LOG_LEVEL, DB_PATH, DRY_RUN

_apscheduler = None
_team_id_map = {}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("bot")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def daily_refresh():
    today = _today()
    log.info("Daily refresh for %s", today)
    sched.schedule_day(_apscheduler, today, _team_id_map)
    db.cleanup_old_games(before_date=_yesterday())


def main():
    if DRY_RUN:
        log.warning("*** DRY RUN MODE — no messages will be posted to Slack ***")

    # Init DB
    db.init_db()

    # Discover / validate ESPN team IDs
    global _apscheduler, _team_id_map
    log.info("Discovering ESPN team IDs…")
    _team_id_map = espn.discover_team_ids()

    # Set up APScheduler with SQLAlchemy job store so jobs survive restarts
    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}"),
    }
    executors = {
        "default": ThreadPoolExecutor(20),
    }
    job_defaults = {
        "misfire_grace_time": 3600,  # don't drop jobs that fire up to 1hr late
        "coalesce": True,
    }
    _apscheduler = BackgroundScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone="UTC",
    )
    _apscheduler.start()
    log.info("Scheduler started")

    # Daily refresh at 06:00 local time
    _apscheduler.add_job(
        daily_refresh,
        "cron",
        hour=6,
        minute=0,
        id="daily_refresh",
        replace_existing=True,
    )

    # Run immediately on startup
    daily_refresh()

    # Graceful shutdown on SIGTERM/SIGINT
    def _shutdown(sig, frame):
        log.info("Shutting down…")
        _apscheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info("Gameday bot running. Press Ctrl+C to stop.")
    signal.pause()


if __name__ == "__main__":
    main()
