import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

import db
import espn
import formatter
import slack_client
import blurb
import odds
import weather
import poller
from config import (
    TEAM_CONFIG,
    HALFTIME_OFFSETS,
    EXPECTED_DURATIONS,
    ODDS_SPORT_KEYS,
    STADIUM_COORDS,
    BLURB_ENABLED,
)

log = logging.getLogger(__name__)


def schedule_day(scheduler: BackgroundScheduler, date_str: str, team_id_map: dict):
    """
    date_str: YYYY-MM-DD
    Fetches games for all configured teams and schedules pre/mid/final jobs.
    """
    espn_date = date_str.replace("-", "")
    already_seen: set[str] = set()

    # Group teams by sport+league to reduce API calls
    groups: dict[tuple, list] = {}
    for team in TEAM_CONFIG:
        key = (team["sport"], team["league"])
        groups.setdefault(key, []).append(team)

    for (sport, league), teams in groups.items():
        team_ids = {team_id_map.get(espn._cache_key(t)) for t in teams if team_id_map.get(espn._cache_key(t))}
        if not team_ids:
            log.warning("No ESPN IDs resolved for %s/%s, skipping", sport, league)
            continue

        try:
            games = espn.get_games_for_date(sport, league, espn_date, team_ids, include_final=True)
        except Exception as exc:
            log.error("Failed to fetch schedule for %s/%s: %s", sport, league, exc)
            continue

        import time as _time
        _time.sleep(1)  # rate-limit ESPN

        for game in games:
            if game.game_id in already_seen:
                continue
            already_seen.add(game.game_id)

            db.upsert_game(
                game_id=game.game_id,
                sport=sport,
                home_team=game.home_team,
                away_team=game.away_team,
                start_time_iso=game.start_time.isoformat(),
                date=date_str,
                home_record=game.home_record,
                away_record=game.away_record,
                broadcasts=",".join(game.broadcasts),
            )

            _schedule_game_jobs(scheduler, game, date_str)


def _schedule_game_jobs(scheduler: BackgroundScheduler, game, date_str: str):
    now = datetime.now(timezone.utc)
    sport = game.sport

    pregame_time = game.start_time - timedelta(hours=1)
    midgame_time = game.start_time + timedelta(hours=HALFTIME_OFFSETS.get(sport, 2.0))
    poller_time = game.start_time + timedelta(hours=EXPECTED_DURATIONS.get(sport, 3.0))

    # Detect missed stages (window passed but not yet posted)
    pregame_missed = not db.is_posted(game.game_id, "pregame") and pregame_time <= now
    midgame_missed = not db.is_posted(game.game_id, "midgame") and midgame_time <= now
    poller_missed = not db.is_posted(game.game_id, "final") and poller_time <= now

    if not db.is_posted(game.game_id, "pregame") and pregame_time > now:
        scheduler.add_job(
            _run_pregame,
            "date",
            run_date=pregame_time,
            args=[game.game_id, sport, game.league],
            id=f"pregame_{game.game_id}",
            replace_existing=True,
        )
        log.info("Scheduled pre-game for %s @ %s at %s UTC", game.away_team, game.home_team, pregame_time)
    elif db.is_posted(game.game_id, "pregame"):
        log.info("Pre-game already posted for %s, skipping schedule", game.game_id)

    if not db.is_posted(game.game_id, "midgame") and midgame_time > now:
        scheduler.add_job(
            _run_midgame,
            "date",
            run_date=midgame_time,
            args=[game.game_id, sport, game.league],
            id=f"midgame_{game.game_id}",
            replace_existing=True,
        )
        log.info("Scheduled mid-game for %s at %s UTC", game.game_id, midgame_time)

    if not db.is_posted(game.game_id, "final") and poller_time > now:
        scheduler.add_job(
            _run_poller,
            "date",
            run_date=poller_time,
            args=[game.game_id, sport, game.league],
            id=f"poller_{game.game_id}",
            replace_existing=True,
        )
        log.info("Scheduled final poller for %s at %s UTC", game.game_id, poller_time)

    # Catch up any stages whose windows have already passed
    if pregame_missed or midgame_missed or poller_missed:
        log.warning(
            "Catch-up needed for %s: pregame=%s midgame=%s final=%s",
            game.game_id, pregame_missed, midgame_missed, poller_missed,
        )
        catchup_time = datetime.now(timezone.utc) + timedelta(seconds=2)
        scheduler.add_job(
            _run_catchup,
            "date",
            run_date=catchup_time,
            args=[game.game_id, sport, game.league, pregame_missed, midgame_missed, poller_missed],
            id=f"catchup_{game.game_id}",
            replace_existing=True,
        )


def _run_pregame(game_id: str, sport: str, league: str):
    if db.is_posted(game_id, "pregame"):
        log.info("Pre-game already posted for %s", game_id)
        return

    log.info("Running pre-game post for %s", game_id)
    row = db.get_game(game_id)
    if not row:
        log.error("Game %s not in DB", game_id)
        return

    try:
        summary = espn.get_game_summary(sport, league, game_id)
    except Exception as exc:
        log.warning("Could not fetch game summary for %s: %s", game_id, exc)
        summary = None

    home_record = row.get("home_record") or (summary.home_record if summary else "")
    away_record = row.get("away_record") or (summary.away_record if summary else "")
    injuries = summary.injuries if summary else []
    series_ctx = summary.series_context if summary else None

    from espn import Game
    from datetime import datetime
    game = Game(
        game_id=row["game_id"],
        sport=sport,
        league=league,
        home_team=row["home_team"],
        away_team=row["away_team"],
        home_team_id="",
        away_team_id="",
        start_time=datetime.fromisoformat(row["start_time"]),
        status="pre",
        series_context=series_ctx,
        broadcasts=(
            [b for b in row.get("broadcasts", "").split(",") if b]
            or (summary.broadcasts if summary else [])
        ),
    )

    # Odds (graceful)
    odds_result = None
    try:
        sport_path = f"{sport}/{league}"
        odds_result = odds.get_odds(sport_path, row["home_team"], row["away_team"])
    except Exception as exc:
        log.warning("Odds fetch failed: %s", exc)

    # Weather (outdoor NFL/MLB only)
    weather_result = None
    try:
        if sport in ("football", "baseball") and row["home_team"] in STADIUM_COORDS:
            weather_result = weather.get_game_weather(row["home_team"], game.start_time)
    except Exception as exc:
        log.warning("Weather fetch failed: %s", exc)

    # Blurb
    blurb_text = ""
    if BLURB_ENABLED:
        injury_summary = (
            ", ".join(f"{i['name']} ({i['team']}) — {i['status']}" for i in injuries[:3])
            if injuries else "None reported"
        )
        try:
            blurb_text = blurb.generate_blurb({
                "away_team": row["away_team"],
                "home_team": row["home_team"],
                "sport": sport,
                "away_record": away_record,
                "home_record": home_record,
                "series_context": series_ctx or "Regular season",
                "injuries": injury_summary,
            })
        except Exception as exc:
            log.warning("Blurb generation failed: %s", exc)

    blocks = formatter.build_pregame_blocks(game=game)
    text = f"Game Day: {row['away_team']} @ {row['home_team']}"
    ts = slack_client.post_message(blocks=blocks, text=text)

    if ts:
        db.save_slack_ts(game_id, ts)
        db.mark_posted(game_id, "pregame")
        log.info("Pre-game posted for %s (ts=%s)", game_id, ts)

        thread_blocks = formatter.build_pregame_thread_blocks(
            game=game,
            home_record=home_record,
            away_record=away_record,
            odds=odds_result,
            weather=weather_result,
            blurb=blurb_text,
        )
        thread_text = f"Pre-game details: {row['away_team']} @ {row['home_team']}"
        slack_client.post_reply(blocks=thread_blocks, text=thread_text, thread_ts=ts)
    else:
        log.error("Pre-game post failed for %s", game_id)


def _run_midgame(game_id: str, sport: str, league: str):
    if db.is_posted(game_id, "midgame"):
        log.info("Mid-game already posted for %s", game_id)
        return

    row = db.get_game(game_id)
    if not row:
        log.error("Game %s not in DB", game_id)
        return

    thread_ts = row.get("slack_ts")
    if not thread_ts:
        log.warning("No slack_ts for %s mid-game update, pre-game may have failed", game_id)
        return

    try:
        if sport == "basketball":
            summary = poller.poll_for_halftime(game_id, sport, league)
        else:
            summary = espn.get_game_summary(sport, league, game_id)
    except Exception as exc:
        log.error("Failed to fetch mid-game summary for %s: %s", game_id, exc)
        return

    if not summary:
        log.warning("No summary returned for mid-game %s", game_id)
        return

    blocks = formatter.build_midgame_blocks(summary, sport)
    text = f"Halftime update: {row['away_team']} @ {row['home_team']}"
    ok = slack_client.post_reply(blocks=blocks, text=text, thread_ts=thread_ts)

    if ok:
        db.mark_posted(game_id, "midgame")
        log.info("Mid-game update posted for %s", game_id)


def _run_poller(game_id: str, sport: str, league: str):
    poller.poll_for_final(game_id, sport, league)


def _run_catchup(game_id: str, sport: str, league: str, do_pregame: bool, do_midgame: bool, do_poll: bool):
    """Run missed stages in order so slack_ts is always set before threaded posts."""
    log.info("Catch-up starting for %s (pregame=%s midgame=%s poll=%s)", game_id, do_pregame, do_midgame, do_poll)
    if do_pregame:
        _run_pregame(game_id, sport, league)
    if do_midgame:
        _run_midgame(game_id, sport, league)
    if do_poll:
        poller.poll_for_final(game_id, sport, league)
