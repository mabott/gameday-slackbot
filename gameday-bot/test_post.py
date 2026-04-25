#!/usr/bin/env python3
"""
Immediately fire pre-game, mid-game, and final posts for a real or synthetic game.

Usage:
    python3 test_post.py                             # synthetic NFL game, all three posts
    python3 test_post.py --sport basketball          # synthetic NBA game
    python3 test_post.py --team "LA Lakers"          # find next real Lakers game
    python3 test_post.py --team "LA Lakers" --historical  # use a real completed Lakers game
    python3 test_post.py --stage pre                 # only the pre-game post
    python3 test_post.py --delay 5                   # seconds between posts (default 3)

Set DRY_RUN=true in .env or environment to print to stdout instead of posting.
"""

import argparse
import copy
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

from config import DRY_RUN, TEAM_CONFIG
import db
import espn
import formatter
import slack_client
import blurb
import odds
import weather
from espn import Game, GameSummary


# ---------------------------------------------------------------------------
# Per-sport synthetic data templates
# Leaders use "{home}" / "{away}" as team name placeholders, resolved at
# runtime from the actual game object.
# ---------------------------------------------------------------------------

_SYNTHETIC = {
    "football": {
        "game": dict(
            sport="football", league="nfl",
            home_team="Green Bay Packers", away_team="Seattle Seahawks",
            home_team_id="9", away_team_id="26",
            broadcasts=["FOX", "NFL+"],
        ),
        "mid": dict(
            period="Halftime", home_score=14, away_score=10,
            home_record="9-4", away_record="8-5",
            leaders=[
                {"name": "J. Love", "stat": "187 yds, 1 TD", "stat_name": "Passing", "team": "{home}"},
                {"name": "G. Smith", "stat": "153 yds, 1 TD", "stat_name": "Passing", "team": "{away}"},
                {"name": "A. Jones", "stat": "62 yds", "stat_name": "Rushing", "team": "{home}"},
            ],
        ),
        "final": dict(
            period="Final", home_score=27, away_score=24,
            home_record="10-4", away_record="8-6",
            leaders=[
                {"name": "J. Love", "stat": "334 yds, 3 TD, 1 INT", "stat_name": "Passing", "team": "{home}"},
                {"name": "G. Smith", "stat": "271 yds, 2 TD", "stat_name": "Passing", "team": "{away}"},
                {"name": "C. Watson", "stat": "9 rec, 112 yds, 1 TD", "stat_name": "Receiving", "team": "{home}"},
                {"name": "K. Walker", "stat": "88 yds, 1 TD", "stat_name": "Rushing", "team": "{away}"},
            ],
        ),
    },
    "basketball": {
        "game": dict(
            sport="basketball", league="nba",
            home_team="Los Angeles Lakers", away_team="Golden State Warriors",
            home_team_id="13", away_team_id="9",
            broadcasts=["ESPN"],
        ),
        "mid": dict(
            period="Halftime", home_score=58, away_score=54,
            home_record="31-18", away_record="28-21",
            leaders=[
                {"name": "A. Davis", "stat": "22 pts", "stat_name": "Points", "team": "{home}"},
                {"name": "S. Curry", "stat": "19 pts", "stat_name": "Points", "team": "{away}"},
                {"name": "D. Green", "stat": "9 reb", "stat_name": "Rebounds", "team": "{away}"},
                {"name": "L. James", "stat": "8 ast", "stat_name": "Assists", "team": "{home}"},
            ],
        ),
        "final": dict(
            period="Final", home_score=118, away_score=112,
            home_record="32-18", away_record="28-22",
            leaders=[
                {"name": "A. Davis", "stat": "38 pts, 14 reb", "stat_name": "Points", "team": "{home}"},
                {"name": "S. Curry", "stat": "34 pts, 7 ast", "stat_name": "Points", "team": "{away}"},
                {"name": "L. James", "stat": "24 pts, 11 ast", "stat_name": "Points", "team": "{home}"},
                {"name": "D. Green", "stat": "12 reb, 8 ast", "stat_name": "Rebounds", "team": "{away}"},
            ],
        ),
    },
    "baseball": {
        "game": dict(
            sport="baseball", league="mlb",
            home_team="Los Angeles Dodgers", away_team="Chicago Cubs",
            home_team_id="19", away_team_id="16",
            broadcasts=["FS1", "Apple TV+"],
        ),
        "mid": dict(
            period="Middle 5th", home_score=3, away_score=2,
            home_record="52-31", away_record="44-39",
            leaders=[
                {"name": "S. Ohtani", "stat": "5 IP, 6 K, 1 ER", "stat_name": "Pitching", "team": "{home}"},
                {"name": "F. Freeman", "stat": "2-3, 1 HR, 2 RBI", "stat_name": "Hitting", "team": "{home}"},
                {"name": "I. Happ", "stat": "1-2, 1 2B, 1 RBI", "stat_name": "Hitting", "team": "{away}"},
            ],
        ),
        "final": dict(
            period="Final", home_score=6, away_score=4,
            home_record="53-31", away_record="44-40",
            leaders=[
                {"name": "S. Ohtani", "stat": "7 IP, 10 K, 2 ER", "stat_name": "Pitching", "team": "{home}"},
                {"name": "F. Freeman", "stat": "3-4, 1 HR, 3 RBI", "stat_name": "Hitting", "team": "{home}"},
                {"name": "M. Betts", "stat": "2-4, 1 HR, 2 RBI", "stat_name": "Hitting", "team": "{home}"},
                {"name": "I. Happ", "stat": "2-4, 1 HR, 2 RBI", "stat_name": "Hitting", "team": "{away}"},
            ],
        ),
    },
    "hockey": {
        "game": dict(
            sport="hockey", league="nhl",
            home_team="Los Angeles Kings", away_team="Seattle Kraken",
            home_team_id="26", away_team_id="55",
            broadcasts=["TNT"],
        ),
        "mid": dict(
            period="End of 2nd", home_score=2, away_score=1,
            home_record="34-22-6", away_record="29-28-5",
            leaders=[
                {"name": "A. Kopitar", "stat": "1G, 1A", "stat_name": "Points", "team": "{home}"},
                {"name": "M. Beniers", "stat": "1G", "stat_name": "Goals", "team": "{away}"},
            ],
            goalie_saves={
                "{home}": {"name": "D. Rittich", "saves": "18"},
                "{away}": {"name": "P. Grubauer", "saves": "16"},
            },
        ),
        "final": dict(
            period="Final", home_score=4, away_score=2,
            home_record="35-22-6", away_record="29-29-5",
            leaders=[
                {"name": "A. Kopitar", "stat": "1G, 2A", "stat_name": "Points", "team": "{home}"},
                {"name": "Q. Hughes", "stat": "2A", "stat_name": "Points", "team": "{away}"},
                {"name": "M. Beniers", "stat": "1G, 1A", "stat_name": "Points", "team": "{away}"},
            ],
            goalie_saves={
                "{home}": {"name": "D. Rittich", "saves": "29"},
                "{away}": {"name": "P. Grubauer", "saves": "24"},
            },
        ),
    },
}


def _resolve(val, home: str, away: str):
    """Recursively replace {home}/{away} placeholders in strings, lists, dicts."""
    if isinstance(val, str):
        return val.replace("{home}", home).replace("{away}", away)
    if isinstance(val, list):
        return [_resolve(v, home, away) for v in val]
    if isinstance(val, dict):
        return {_resolve(k, home, away): _resolve(v, home, away) for k, v in val.items()}
    return val


def _make_synthetic_game(sport: str) -> Game:
    data = _SYNTHETIC.get(sport, _SYNTHETIC["football"])["game"]
    return Game(
        game_id=f"test-synthetic-{sport}",
        start_time=datetime.now(timezone.utc) + timedelta(hours=1),
        status="pre",
        series_context=None,
        **data,
    )


def _make_synthetic_summary(game: Game, stage: str) -> GameSummary:
    sport_data = _SYNTHETIC.get(game.sport, _SYNTHETIC["football"])
    tmpl = copy.deepcopy(sport_data[stage])
    home, away = game.home_team, game.away_team
    return GameSummary(
        game_id=game.game_id,
        status="in" if stage == "mid" else "post",
        home_team=home,
        away_team=away,
        home_score=tmpl["home_score"],
        away_score=tmpl["away_score"],
        home_record=tmpl.get("home_record", ""),
        away_record=tmpl.get("away_record", ""),
        period=tmpl["period"],
        leaders=_resolve(tmpl.get("leaders", []), home, away),
        goalie_saves=_resolve(tmpl.get("goalie_saves", {}), home, away),
        series_context=game.series_context,
    )


# ---------------------------------------------------------------------------
# Game finders
# ---------------------------------------------------------------------------

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
            log.info("Found upcoming game on %s: %s @ %s", date, games[0].away_team, games[0].home_team)
            return games[0]

    log.warning("No upcoming games found for %s in the next 7 days", team_cfg["name"])
    return None


def find_historical_game(team_name: str) -> Optional[tuple]:
    """
    Find a recently completed game (up to 14 days back) and return
    (Game, GameSummary) with the full box score.
    """
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
    for days_ago in range(1, 15):
        date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y%m%d")
        games = espn.get_games_for_date(sport, league, date, {team_id}, include_final=True)
        time.sleep(0.5)
        completed = [g for g in games if g.status == "post"]
        if not completed:
            continue
        game = completed[0]
        log.info("Found completed game on %s: %s @ %s", date, game.away_team, game.home_team)
        summary = espn.get_game_summary(sport, league, game.game_id)
        if summary:
            return game, summary
        log.warning("Couldn't fetch summary for %s, trying further back", game.game_id)

    log.warning("No completed games found for %s in the last 14 days", team_cfg["name"])
    return None


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_test(
    game: Game,
    stages: list,
    delay: int,
    historical_summary: Optional[GameSummary] = None,
):
    db.init_db()

    if DRY_RUN:
        log.warning("*** DRY RUN — output goes to stdout, not Slack ***")

    thread_ts = None

    # --- Pre-game ---
    if "pre" in stages:
        log.info("Firing pre-game post for %s @ %s", game.away_team, game.home_team)

        summary = historical_summary
        if not summary:
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

        injury_summary = (
            ", ".join(f"{i['name']} ({i['team']}) — {i['status']}" for i in injuries[:3])
            if injuries else "None reported"
        )
        blurb_text = ""
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

        if historical_summary:
            mid_summary = historical_summary
        else:
            mid_summary = None
            try:
                live = espn.get_game_summary(game.sport, game.league, game.game_id)
                if live:
                    mid_summary = live
            except Exception:
                pass
            if not mid_summary:
                log.info("No live mid-game data, using synthetic %s data", game.sport)
                mid_summary = _make_synthetic_summary(game, "mid")

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

        if historical_summary and historical_summary.status == "post":
            final_summary = historical_summary
        else:
            final_summary = None
            try:
                live = espn.get_game_summary(game.sport, game.league, game.game_id)
                if live and live.status == "post":
                    final_summary = live
            except Exception:
                pass
            if not final_summary:
                log.info("No live final data, using synthetic %s data", game.sport)
                final_summary = _make_synthetic_summary(game, "final")

        blocks = formatter.build_final_blocks(final_summary, game.sport)
        text = f"Final: {game.away_team} {final_summary.away_score} — {game.home_team} {final_summary.home_score}"
        slack_client.post_reply(blocks=blocks, text=text, thread_ts=thread_ts)
        log.info("Final posted")

    log.info("Test post complete.")


def main():
    parser = argparse.ArgumentParser(description="Fire test Slack posts immediately.")
    parser.add_argument("--team", help="Team name to find a game for (e.g. 'Lakers', 'Dodgers')")
    parser.add_argument(
        "--historical",
        action="store_true",
        help="Use a real completed game from the last 14 days (requires --team)",
    )
    parser.add_argument(
        "--sport",
        choices=["football", "basketball", "baseball", "hockey"],
        default="football",
        help="Sport for synthetic game when no --team is given (default: football)",
    )
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
    historical_summary = None

    if args.historical:
        if not args.team:
            log.error("--historical requires --team")
            sys.exit(1)
        result = find_historical_game(args.team)
        if not result:
            sys.exit(1)
        game, historical_summary = result
    elif args.team:
        game = find_real_game(args.team)
        if not game:
            sys.exit(1)
    else:
        log.info("No --team specified, using synthetic %s game data", args.sport)
        game = _make_synthetic_game(args.sport)

    run_test(game, stages, args.delay, historical_summary=historical_summary)


if __name__ == "__main__":
    main()
