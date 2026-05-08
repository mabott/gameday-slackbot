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
    ODDS_SPORT_KEYS,
    STADIUM_COORDS,
    BLURB_ENABLED,
)

log = logging.getLogger(__name__)


def schedule_day(scheduler: BackgroundScheduler, date_str: str, team_id_map: dict):
    """
    date_str: YYYY-MM-DD
    Fetches games for all configured teams and schedules pregame and in-game jobs.
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

    # Pregame: schedule or catch up immediately if window has passed
    if not db.is_posted(game.game_id, "pregame"):
        run_at = pregame_time if pregame_time > now else now + timedelta(seconds=2)
        scheduler.add_job(
            _run_pregame,
            "date",
            run_date=run_at,
            args=[game.game_id, sport, game.league],
            id=f"pregame_{game.game_id}",
            replace_existing=True,
        )
        if pregame_time <= now:
            log.warning("Pre-game missed for %s — scheduling catch-up immediately", game.game_id)
        else:
            log.info("Scheduled pre-game for %s @ %s at %s UTC", game.away_team, game.home_team, pregame_time)
    else:
        log.info("Pre-game already posted for %s", game.game_id)

    # In-game poller: starts at game time, handles period updates and final.
    # If game has already started (or is over), start immediately.
    if not db.is_posted(game.game_id, "final"):
        run_at = game.start_time if game.start_time > now else now + timedelta(seconds=10)
        scheduler.add_job(
            _run_in_game,
            "date",
            run_date=run_at,
            args=[game.game_id, sport, game.league],
            id=f"ingame_{game.game_id}",
            replace_existing=True,
        )
        if game.start_time <= now:
            log.warning("In-game poller for %s starting immediately (game already started or finished)", game.game_id)
        else:
            log.info("Scheduled in-game poller for %s at %s UTC", game.game_id, game.start_time)
    else:
        log.info("Final already posted for %s, skipping in-game schedule", game.game_id)


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


def _run_in_game(game_id: str, sport: str, league: str):
    poller.poll_in_game_updates(game_id, sport, league)
