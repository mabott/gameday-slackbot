import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import yaml

load_dotenv()

log = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TZ = os.environ.get("TZ", "America/Los_Angeles")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
BLURB_ENABLED = os.environ.get("BLURB_ENABLED", "false").lower() == "true"

DB_PATH = os.environ.get("DB_PATH", "gameday.db")
ESPN_ID_CACHE_PATH = os.environ.get("ESPN_ID_CACHE_PATH", "espn_ids.json")

TEAMS_FILE = os.environ.get("TEAMS_FILE", str(Path(__file__).parent / "teams.yaml"))

VALID_SPORTS = {"basketball", "baseball", "football", "hockey"}
VALID_LEAGUES = {"nba", "mlb", "nfl", "nhl"}


def _load_teams(path: str) -> tuple[list[dict], dict]:
    with open(path) as f:
        data = yaml.safe_load(f)

    teams = []
    stadium_coords = {}
    seen: dict[tuple, str] = {}  # (sport, league, shortname) -> full name, for collision detection

    for entry in data.get("teams", []):
        name = entry.get("name", "").strip()
        sport = entry.get("sport", "").strip().lower()
        league = entry.get("league", "").strip().lower()

        if not name:
            log.warning("teams.yaml: skipping entry with no name")
            continue
        if sport not in VALID_SPORTS:
            log.warning("teams.yaml: unknown sport '%s' for %s — skipping", sport, name)
            continue
        if league not in VALID_LEAGUES:
            log.warning("teams.yaml: unknown league '%s' for %s — skipping", league, name)
            continue

        # Warn about teams with the same nickname in the same sport/league
        nickname = name.split()[-1].lower()
        key = (sport, league, nickname)
        if key in seen:
            log.warning(
                "teams.yaml: '%s' and '%s' share the nickname '%s' in %s/%s — "
                "ESPN ID matching may be ambiguous",
                seen[key], name, nickname, sport, league,
            )
        seen[key] = name

        teams.append({"name": name, "sport": sport, "league": league, "espn_id": None})

        coords = entry.get("stadium_coords")
        if coords and isinstance(coords, list) and len(coords) == 2:
            stadium_coords[name] = (float(coords[0]), float(coords[1]))
        else:
            stadium_coords[name] = None

    return teams, stadium_coords


TEAM_CONFIG, STADIUM_COORDS = _load_teams(TEAMS_FILE)

# Offset from game start to post the mid-game update (hours)
HALFTIME_OFFSETS = {
    "football": 2.5,
    "basketball": 1.25,
    "baseball": 2.5,
    "hockey": 1.25,
}

# Offset from game start to begin polling for final score (hours)
EXPECTED_DURATIONS = {
    "football": 3.5,
    "basketball": 2.5,
    "baseball": 3.5,
    "hockey": 2.75,
}

SPORT_EMOJIS = {
    "football": "🏈",
    "basketball": "🏀",
    "baseball": "⚾",
    "hockey": "🏒",
}

ODDS_SPORT_KEYS = {
    "football/nfl": "americanfootball_nfl",
    "basketball/nba": "basketball_nba",
    "baseball/mlb": "baseball_mlb",
    "hockey/nhl": "icehockey_nhl",
}

CLAUDE_MODEL = "claude-sonnet-4-6"
