import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

from config import TEAM_CONFIG, ESPN_ID_CACHE_PATH

log = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
_session = requests.Session()
_session.headers.update({"User-Agent": "gameday-bot/1.0"})


@dataclass
class Game:
    game_id: str
    sport: str
    league: str
    home_team: str
    away_team: str
    home_team_id: str
    away_team_id: str
    start_time: datetime  # UTC
    status: str           # "pre", "in", "post"
    home_score: int = 0
    away_score: int = 0
    broadcasts: list = field(default_factory=list)
    series_context: Optional[str] = None
    venue: str = ""
    home_record: str = ""
    away_record: str = ""


@dataclass
class GameSummary:
    game_id: str
    status: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    home_record: str
    away_record: str
    period: str
    period_num: int = 0       # current period number (0 if unknown)
    clock_secs: float = 0.0   # seconds remaining on game clock
    home_abbr: str = ""       # ESPN team abbreviation, e.g. "LAD", "OKC"
    away_abbr: str = ""
    leaders: list = field(default_factory=list)
    goalie_saves: dict = field(default_factory=dict)
    series_context: Optional[str] = None
    injuries: list = field(default_factory=list)
    plays: list = field(default_factory=list)
    broadcasts: list = field(default_factory=list)


@dataclass
class Record:
    wins: int
    losses: int
    ties: int = 0

    def __str__(self):
        if self.ties:
            return f"{self.wins}-{self.losses}-{self.ties}"
        return f"{self.wins}-{self.losses}"


def _get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            resp = _session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            log.warning("ESPN request failed (attempt %d/%d): %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


# ---------------------------------------------------------------------------
# Team ID discovery
# ---------------------------------------------------------------------------

def _fetch_all_teams(sport, league):
    url = f"{ESPN_BASE}/{sport}/{league}/teams"
    data = _get(url, params={"limit": 100})
    if not data:
        return []
    return data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])


def _name_matches(config_name: str, espn_display: str, espn_short: str) -> bool:
    cn = config_name.lower()
    ed = espn_display.lower()
    es = espn_short.lower()
    # Exact or substring match in either direction
    return cn == ed or cn in ed or ed in cn or es in cn


def _cache_key(team: dict) -> str:
    """Unique cache key that includes sport+league to disambiguate shared nicknames."""
    return f"{team['name']}|{team['sport']}|{team['league']}"


def discover_team_ids() -> dict:
    """
    Fetch ESPN teams for each sport/league, match against TEAM_CONFIG by name,
    and return a mapping of cache_key → espn_id. Results are cached to disk.

    Use team_id_map.get(_cache_key(team)) to look up a specific team.
    """
    if os.path.exists(ESPN_ID_CACHE_PATH):
        with open(ESPN_ID_CACHE_PATH) as f:
            cached = json.load(f)
        log.info("Loaded ESPN ID cache from %s", ESPN_ID_CACHE_PATH)
        return cached

    log.info("Discovering ESPN team IDs…")
    id_map: dict[str, str] = {}

    # Group teams by sport/league to minimise API calls
    sport_league_groups: dict[tuple, list] = {}
    for team in TEAM_CONFIG:
        key = (team["sport"], team["league"])
        sport_league_groups.setdefault(key, []).append(team)

    for (sport, league), teams in sport_league_groups.items():
        log.info("Fetching teams for %s/%s", sport, league)
        espn_teams = _fetch_all_teams(sport, league)
        time.sleep(1)  # be polite

        for entry in espn_teams:
            t = entry.get("team", {})
            espn_id = t.get("id", "")
            display = t.get("displayName", "")
            short = t.get("shortDisplayName", "")
            for team in teams:
                if _name_matches(team["name"], display, short):
                    ck = _cache_key(team)
                    if ck in id_map:
                        log.warning(
                            "Duplicate ESPN ID match for %s (%s/%s): had %s, now %s (%s)",
                            team["name"], sport, league, id_map[ck], espn_id, display,
                        )
                    else:
                        id_map[ck] = espn_id
                        log.info("  ✓ %s [%s/%s] → ESPN ID %s (%s)", team["name"], sport, league, espn_id, display)

    # Report any teams that weren't matched
    for team in TEAM_CONFIG:
        if _cache_key(team) not in id_map:
            log.error("  ✗ Could not find ESPN ID for: %s [%s/%s]", team["name"], team["sport"], team["league"])

    with open(ESPN_ID_CACHE_PATH, "w") as f:
        json.dump(id_map, f, indent=2)
    log.info("ESPN ID cache saved to %s", ESPN_ID_CACHE_PATH)
    return id_map


def refresh_team_ids():
    """Force re-discovery by deleting the cache and rediscovering."""
    if os.path.exists(ESPN_ID_CACHE_PATH):
        os.remove(ESPN_ID_CACHE_PATH)
    return discover_team_ids()


# ---------------------------------------------------------------------------
# Schedule / scoreboard
# ---------------------------------------------------------------------------

def get_games_for_date(
    sport: str,
    league: str,
    date: str,
    team_ids: set[str],
    include_final: bool = False,
) -> list[Game]:
    """
    date: YYYYMMDD string
    team_ids: set of ESPN team IDs to filter for
    include_final: if True, also return completed games (status="post")
    """
    url = f"{ESPN_BASE}/{sport}/{league}/scoreboard"
    data = _get(url, params={"dates": date})
    if not data:
        return []

    _COMPLETE = ("STATUS_FINAL", "STATUS_FINAL_OT", "STATUS_FINAL_PENALTY")

    games = []
    for event in data.get("events", []):
        competitors = event.get("competitions", [{}])[0].get("competitors", [])
        comp_ids = {c["team"]["id"] for c in competitors}
        if not comp_ids.intersection(team_ids):
            continue

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[-1])

        start_raw = event.get("date", "")
        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        except ValueError:
            log.warning("Unparseable date for event %s: %s", event.get("id"), start_raw)
            continue

        status_type = event.get("status", {}).get("type", {}).get("name", "STATUS_SCHEDULED")
        if status_type in ("STATUS_POSTPONED", "STATUS_CANCELED"):
            continue
        is_complete = status_type in _COMPLETE
        if is_complete and not include_final:
            continue

        broadcasts = [
            b.get("names", [""])[0]
            for b in event.get("competitions", [{}])[0].get("broadcasts", [])
        ]

        series_ctx = None
        series = event.get("competitions", [{}])[0].get("series")
        if isinstance(series, list):
            series = next((s for s in series if s.get("type") == "playoff"), series[0] if series else None)
        series_ctx = _series_context(series, team_hints=competitors)

        venue = event.get("competitions", [{}])[0].get("venue", {}).get("fullName", "")

        def _record(competitor):
            recs = competitor.get("records", [])
            overall = next((r for r in recs if r.get("type") == "total"), recs[0] if recs else {})
            return overall.get("summary", "")

        games.append(Game(
            game_id=event["id"],
            sport=sport,
            league=league,
            home_team=home["team"]["displayName"],
            away_team=away["team"]["displayName"],
            home_team_id=home["team"]["id"],
            away_team_id=away["team"]["id"],
            start_time=start_dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc),
            status="post" if is_complete else "pre",
            home_score=int(home.get("score", 0) or 0),
            away_score=int(away.get("score", 0) or 0),
            broadcasts=[b for b in broadcasts if b],
            series_context=series_ctx,
            venue=venue,
            home_record=_record(home),
            away_record=_record(away),
        ))

    return games


# ---------------------------------------------------------------------------
# Game summary (live + final)
# ---------------------------------------------------------------------------

def get_game_summary(sport: str, league: str, event_id: str) -> Optional[GameSummary]:
    url = f"{ESPN_BASE}/{sport}/{league}/summary"
    data = _get(url, params={"event": event_id})
    if not data:
        return None

    boxscore = data.get("boxscore", {})
    header_comps = data.get("header", {}).get("competitions", [{}])[0].get("competitors", [])

    # Scores only exist in header competitors; stats/records live in boxscore teams
    competitors = boxscore.get("teams", []) or header_comps

    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    h_score = next((c for c in header_comps if c.get("homeAway") == "home"), {})
    a_score = next((c for c in header_comps if c.get("homeAway") == "away"), {})

    def team_name(c):
        return c.get("team", {}).get("displayName", "")

    def team_abbr(c):
        return c.get("team", {}).get("abbreviation", "")

    def score(c):
        return int(c.get("score", 0) or 0)

    def record(c):
        rec = c.get("records", [{}])
        overall = next((r for r in rec if r.get("type") == "total"), rec[0] if rec else {})
        return overall.get("summary", "")

    status_detail = data.get("header", {}).get("competitions", [{}])[0].get("status", {})
    status_name = status_detail.get("type", {}).get("name", "")
    period_text = status_detail.get("type", {}).get("shortDetail", "")
    try:
        period_num = int(status_detail.get("period", 0) or 0)
    except ValueError:
        period_num = 0
    try:
        clock_secs = float(status_detail.get("clock", 0.0) or 0.0)
    except ValueError:
        clock_secs = 0.0

    # Leaders
    leaders = []
    for leader_group in data.get("leaders", []):
        for leader in leader_group.get("leaders", []):
            athlete = leader.get("athlete", {})
            leaders.append({
                "name": athlete.get("displayName", ""),
                "stat": leader.get("displayValue", ""),
                "stat_name": leader_group.get("displayName", ""),
                "team": athlete.get("team", {}).get("displayName", ""),
            })

    # NHL goalie saves
    goalie_saves = {}
    for team_stats in boxscore.get("players", []):
        tname = team_stats.get("team", {}).get("displayName", "")
        for stat_group in team_stats.get("statistics", []):
            if stat_group.get("name") == "goalies":
                for player in stat_group.get("athletes", []):
                    pname = player.get("athlete", {}).get("displayName", "")
                    stats = player.get("stats", [])
                    # ESPN returns saves as a stat in the list; find by position
                    keys = stat_group.get("keys", [])
                    saves_idx = keys.index("saves") if "saves" in keys else -1
                    if saves_idx >= 0 and saves_idx < len(stats):
                        goalie_saves[tname] = {"name": pname, "saves": stats[saves_idx]}

    # Injuries
    injuries = []
    for inj in data.get("injuries", []):
        for report in inj.get("injuries", []):
            athlete = report.get("athlete", {})
            injuries.append({
                "name": athlete.get("displayName", ""),
                "team": inj.get("team", {}).get("displayName", ""),
                "status": report.get("status", ""),
                "detail": report.get("detail", ""),
            })

    series_ctx = None
    series = data.get("header", {}).get("competitions", [{}])[0].get("series")
    if isinstance(series, list):
        series = next((s for s in series if s.get("type") == "playoff"), series[0] if series else None)
    series_ctx = _series_context(series, team_hints=header_comps)

    broadcasts = [
        b.get("names", [""])[0]
        for b in data.get("header", {}).get("competitions", [{}])[0].get("broadcasts", [])
    ]
    broadcasts = [b for b in broadcasts if b]

    is_final = status_name in ("STATUS_FINAL", "STATUS_FINAL_OT", "STATUS_FINAL_PENALTY")

    return GameSummary(
        game_id=event_id,
        status="post" if is_final else "in",
        home_team=team_name(home),
        away_team=team_name(away),
        home_score=score(h_score),
        away_score=score(a_score),
        home_record=record(home),
        away_record=record(away),
        period=period_text,
        period_num=period_num,
        clock_secs=clock_secs,
        home_abbr=team_abbr(h_score),
        away_abbr=team_abbr(a_score),
        leaders=leaders,
        goalie_saves=goalie_saves,
        series_context=series_ctx,
        injuries=injuries,
        plays=data.get("plays", []),
        broadcasts=broadcasts,
    )


def scores_by_period(plays: list) -> dict:
    """
    Return {period_num: (cumulative_away, cumulative_home)} using the last play of each period.
    Scores are running totals — subtract adjacent periods to get per-period deltas.
    Works for all sports.
    """
    result = {}
    for play in plays:
        num = play.get("period", {}).get("number")
        if num is not None:
            result[num] = (
                int(play.get("awayScore", 0) or 0),
                int(play.get("homeScore", 0) or 0),
            )
    return result


def last_goal_from_plays(plays: list, after_index: int) -> Optional[dict]:
    """
    Scan plays[after_index:] for a hockey goal event. Returns a dict with scorer
    name, team, and the play index (so the caller can advance after_index), or None.
    """
    for i in range(after_index, len(plays)):
        play = plays[i]
        if "goal" in play.get("type", {}).get("text", "").lower():
            participants = play.get("participants", [])
            scorer = (
                participants[0].get("athlete", {}).get("displayName", "Unknown")
                if participants else "Unknown"
            )
            return {
                "scorer": scorer,
                "team": play.get("team", {}).get("displayName", ""),
                "play_index": i,
            }
    return None


def baseball_stretch_scores(plays: list) -> Optional[tuple]:
    """Return (away_score, home_score) at the 7th inning stretch, or None."""
    for play in reversed(plays):
        period = play.get("period", {})
        if period.get("number") == 7 and period.get("type") == "Mid":
            return play.get("awayScore", 0), play.get("homeScore", 0)
    return None


def basketball_halftime_scores(plays: list) -> Optional[tuple]:
    """Return (away_score, home_score) at the end of the 2nd quarter, or None."""
    for play in reversed(plays):
        if play.get("period", {}).get("number") == 2:
            return play.get("awayScore", 0), play.get("homeScore", 0)
    return None


def _series_context(series: dict, team_hints: list = None) -> Optional[str]:
    """
    Build a human-readable series context from the ESPN series object.
    team_hints: list of game competitor dicts (from scoreboard or header) used to
    resolve team names by ID when the series competitors carry no name fields.
    """
    if not series or not isinstance(series, dict):
        return None
    log.info("ESPN series object: %s", series)

    # Build ID → short name map from the game's own competitor data
    hint_map: dict[str, str] = {}
    for c in (team_hints or []):
        tid = c.get("team", {}).get("id") or c.get("id")
        tname = (c.get("team", {}).get("shortDisplayName") or
                 c.get("team", {}).get("abbreviation") or
                 c.get("team", {}).get("displayName") or "")
        if tid and tname:
            hint_map[tid] = tname

    def _name(c: dict) -> str:
        team = c.get("team", {})
        name = (team.get("shortDisplayName") or team.get("abbreviation") or
                team.get("displayName") or team.get("name") or
                c.get("shortDisplayName") or c.get("abbreviation") or
                c.get("displayName") or c.get("name") or "")
        if not name:
            cid = c.get("id") or team.get("id")
            name = hint_map.get(cid, "")
        return name

    competitors = series.get("competitors", [])
    if len(competitors) == 2:
        c0, c1 = competitors[0], competitors[1]
        w0 = int(c0.get("wins", 0))
        w1 = int(c1.get("wins", 0))
        name0, name1 = _name(c0), _name(c1)
        if not name0 and not name1:
            log.warning("Series: could not resolve team names (keys: %s); falling back to ESPN summary", list(c0.keys()))
            return series.get("summary") or None
        if w0 == w1:
            return f"Series tied {w0}-{w1}"
        leader, lw, tw = (name0, w0, w1) if w0 > w1 else (name1, w1, w0)
        verb = "win" if max(w0, w1) >= 4 else "lead"
        return f"{leader} {verb} series {lw}-{tw}"

    log.warning("Series: unexpected competitor count (%d); falling back to ESPN summary", len(competitors))
    return series.get("summary") or None


def get_team_record(sport: str, league: str, team_id: str) -> Optional[Record]:
    url = f"{ESPN_BASE}/{sport}/{league}/teams/{team_id}"
    data = _get(url)
    if not data:
        return None
    team = data.get("team", {})
    record_data = team.get("record", {}).get("items", [])
    overall = next((r for r in record_data if r.get("type") == "total"), None)
    if not overall:
        return None
    stats = {s["name"]: s["value"] for s in overall.get("stats", [])}
    return Record(
        wins=int(stats.get("wins", 0)),
        losses=int(stats.get("losses", 0)),
        ties=int(stats.get("ties", 0)),
    )
