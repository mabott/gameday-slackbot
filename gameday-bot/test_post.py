#!/usr/bin/env python3
"""
Immediately fire pre-game, mid-game, and final posts for a real or synthetic game.

Usage:
    python3 test_post.py                        # synthetic game, all three posts
    python3 test_post.py --team "LA Dodgers"    # find next real Dodgers game
    python3 test_post.py --stage pre            # only the pre-game post
    python3 test_post.py --delay 5              # seconds between posts (default 3)

Set DRY_RUN=true in .env or environment to print to stdout instead of posting.
"""

import argparse
import time
import sys
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("test_post")

from config import DRY_RUN, TEAM_CONFIG, BLURB_ENABLED
import db
import espn
import formatter
import slack_client
import blurb
import odds
import weather
from espn import Game, GameSummary


SYNTHETIC_GAME = Game(
    game_id="test-synthetic-001",
    sport="football",
    league="nfl",
    home_team="Green Bay Packers",
    away_team="Seattle Seahawks",
    home_team_id="9",
    away_team_id="26",
    start_time=datetime.now(timezone.utc) + timedelta(hours=1),
    status="pre",
    broadcasts=["FOX", "NFL+"],
    series_context=None,
)

SYNTHETIC_SUMMARY_MID = GameSummary(
    game_id="test-synthetic-001",
    status="in",
    home_team="Green Bay Packers",
    away_team="Seattle Seahawks",
    home_score=14,
    away_score=10,
    home_record="9-4",
    away_record="8-5",
    period="Halftime",
    leaders=[
        {"name": "Geno Smith", "stat": "187 yds, 1 TD", "stat_name": "Passing", "team": "Seattle Seahawks"},
        {"name": "Jordan Love", "stat": "203 yds, 2 TD", "stat_name": "Passing", "team": "Green Bay Packers"},
        {"name": "Kenneth Walker III", "stat": "62 yds", "stat_name": "Rushing", "team": "Seattle Seahawks"},
    ],
    series_context=None,
)

SYNTHETIC_SUMMARY_FINAL = GameSummary(
    game_id="test-synthetic-001",
    status="post",
    home_team="Green Bay Packers",
    away_team="Seattle Seahawks",
    home_score=27,
    away_score=24,
    home_record="10-4",
    away_record="8-6",
    period="Final",
    leaders=[
        {"name": "Jordan Love", "stat": "334 yds, 3 TD, 1 INT", "stat_name": "Passing", "team": "Green Bay Packers"},
        {"name": "Geno Smith", "stat": "271 yds, 2 TD", "stat_name": "Passing", "team": "Seattle Seahawks"},
        {"name": "Christian Watson", "stat": "9 rec, 112 yds, 1 TD", "stat_name": "Receiving", "team": "Green Bay Packers"},
        {"name": "Kenneth Walker III", "stat": "88 yds, 1 TD", "stat_name": "Rushing", "team": "Seattle Seahawks"},
    ],
    series_context=None,
)


def find_real_game(team_name: str) -> Optional[Game]:
    """Find the next upcoming game for a team within the next 7 days."""
    team_cfg = next((t for t in TEAM_CONFIG if team_name.lower() in t["name"].lower()), None)
    if not team_cfg:
        log.error("Team '%s' not found in TEAM_CONFIG", team_name)
        return None

    id_map = espn.discover_team_ids()
    team_id = id_map.get(espn._cache_key(team_cfg))
    if not team_id:
        log.error("No ESPN ID for %s", team_cfg["name"])
        return None

    sport, league = team_cfg["sport"], team_cfg["league"]
    for days_ahead in range(8):
        date = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).strftime("%Y%m%d")
        games = espn.get_games_for_date(sport, league, date, {team_id})
        time.sleep(0.5)
        if games:
            log.info("Found game on %s: %s @ %s", date, games[0].away_team, games[0].home_team)
            return games[0]

    log.warning("No upcoming games found for %s in the next 7 days", team_cfg["name"])
    return None


def run_test(game: Game, stages: list[str], delay: int):
    db.init_db()

    if DRY_RUN:
        log.warning("*** DRY RUN — output goes to stdout, not Slack ***")

    thread_ts = None

    # --- Pre-game ---
    if "pre" in stages:
        log.info("Firing pre-game post for %s @ %s", game.away_team, game.home_team)

        summary = None
        try:
            summary = espn.get_game_summary(game.sport, game.league, game.game_id)
        except Exception:
            pass

        home_record = summary.home_record if summary else "N/A"
        away_record = summary.away_record if summary else "N/A"
        injuries = summary.injuries if summary else []
        series_ctx = summary.series_context if summary else game.series_context

        odds_result = None
        try:
            odds_result = odds.get_odds(f"{game.sport}/{game.league}", game.home_team, game.away_team)
        except Exception:
            pass

        weather_result = None
        try:
            weather_result = weather.get_game_weather(game.home_team, game.start_time)
        except Exception:
            pass

        blurb_text = ""
        if BLURB_ENABLED:
            injury_summary = (
                ", ".join(f"{i['name']} ({i['team']}) — {i['status']}" for i in injuries[:3])
                if injuries else "None reported"
            )
            try:
                blurb_text = blurb.generate_blurb({
                    "away_team": game.away_team,
                    "home_team": game.home_team,
                    "sport": game.sport,
                    "away_record": away_record,
                    "home_record": home_record,
                    "series_context": series_ctx or "Regular season",
                    "injuries": injury_summary,
                })
            except Exception as exc:
                log.warning("Blurb skipped: %s", exc)

        blocks = formatter.build_pregame_blocks(
            game=game,
            home_record=home_record,
            away_record=away_record,
            odds=odds_result,
            weather=weather_result,
            blurb=blurb_text,
        )
        text = f"Game Day: {game.away_team} @ {game.home_team}"
        thread_ts = slack_client.post_message(blocks=blocks, text=text)
        log.info("Pre-game posted (ts=%s)", thread_ts)

        if ("mid" in stages or "final" in stages) and thread_ts:
            log.info("Waiting %ds before mid-game post…", delay)
            time.sleep(delay)

    # --- Mid-game ---
    if "mid" in stages and thread_ts:
        log.info("Firing mid-game post")
        mid_summary = SYNTHETIC_SUMMARY_MID
        # For real games try to fetch live data, fall back to synthetic
        if game.game_id != "test-synthetic-001":
            try:
                live = espn.get_game_summary(game.sport, game.league, game.game_id)
                if live:
                    mid_summary = live
            except Exception:
                pass

        blocks = formatter.build_midgame_blocks(mid_summary, game.sport)
        text = f"Halftime update: {game.away_team} @ {game.home_team}"
        slack_client.post_reply(blocks=blocks, text=text, thread_ts=thread_ts)
        log.info("Mid-game posted")

        if "final" in stages:
            log.info("Waiting %ds before final post…", delay)
            time.sleep(delay)

    # --- Final ---
    if "final" in stages and thread_ts:
        log.info("Firing final post")
        final_summary = SYNTHETIC_SUMMARY_FINAL
        if game.game_id != "test-synthetic-001":
            try:
                live = espn.get_game_summary(game.sport, game.league, game.game_id)
                if live and live.status == "post":
                    final_summary = live
            except Exception:
                pass

        blocks = formatter.build_final_blocks(final_summary, game.sport)
        text = f"Final: {game.away_team} {final_summary.away_score} — {game.home_team} {final_summary.home_score}"
        slack_client.post_reply(blocks=blocks, text=text, thread_ts=thread_ts)
        log.info("Final posted")

    log.info("Test post complete.")


def main():
    parser = argparse.ArgumentParser(description="Fire test Slack posts immediately.")
    parser.add_argument("--team", help="Team name to find a real upcoming game (e.g. 'Dodgers')")
    parser.add_argument(
        "--stage",
        choices=["pre", "mid", "final", "all"],
        default="all",
        help="Which post(s) to fire (default: all)",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=3,
        help="Seconds between posts when firing all stages (default: 3)",
    )
    args = parser.parse_args()

    stages = ["pre", "mid", "final"] if args.stage == "all" else [args.stage]

    if args.team:
        game = find_real_game(args.team)
        if not game:
            sys.exit(1)
    else:
        log.info("No --team specified, using synthetic game data")
        game = SYNTHETIC_GAME

    run_test(game, stages, args.delay)


if __name__ == "__main__":
    main()
