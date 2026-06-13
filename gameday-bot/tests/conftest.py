import os
import sys
from pathlib import Path

# Must precede any project imports so config._load_teams() finds the file.
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("TEAMS_FILE", str(Path(__file__).parent.parent / "teams.yaml.example"))

from datetime import datetime, timezone

import pytest

import db
from espn import Game, GameSummary
from odds import OddsResult
from weather import WeatherResult


# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()


# ---------------------------------------------------------------------------
# Game fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def football_game():
    return Game(
        game_id="test-nfl-001",
        sport="football",
        league="nfl",
        home_team="Green Bay Packers",
        away_team="Seattle Seahawks",
        home_team_id="9",
        away_team_id="26",
        start_time=datetime(2026, 1, 10, 20, 0, 0, tzinfo=timezone.utc),
        status="pre",
        broadcasts=["FOX", "NFL+"],
        venue="Lambeau Field",
        home_record="10-4",
        away_record="8-6",
    )


@pytest.fixture
def basketball_game():
    return Game(
        game_id="test-nba-001",
        sport="basketball",
        league="nba",
        home_team="Los Angeles Lakers",
        away_team="Golden State Warriors",
        home_team_id="13",
        away_team_id="9",
        start_time=datetime(2026, 1, 10, 3, 30, 0, tzinfo=timezone.utc),
        status="pre",
        broadcasts=["ESPN"],
        venue="Crypto.com Arena",
        home_record="31-18",
        away_record="28-21",
    )


@pytest.fixture
def hockey_game():
    return Game(
        game_id="test-nhl-001",
        sport="hockey",
        league="nhl",
        home_team="Los Angeles Kings",
        away_team="Seattle Kraken",
        home_team_id="26",
        away_team_id="55",
        start_time=datetime(2026, 1, 10, 2, 0, 0, tzinfo=timezone.utc),
        status="pre",
        broadcasts=["TNT"],
        venue="Crypto.com Arena",
        home_record="34-22-6",
        away_record="29-28-5",
    )


@pytest.fixture
def baseball_game():
    return Game(
        game_id="test-mlb-001",
        sport="baseball",
        league="mlb",
        home_team="Los Angeles Dodgers",
        away_team="Chicago Cubs",
        home_team_id="19",
        away_team_id="16",
        start_time=datetime(2026, 4, 15, 19, 10, 0, tzinfo=timezone.utc),
        status="pre",
        broadcasts=["FS1"],
        venue="Dodger Stadium",
        home_record="52-31",
        away_record="44-39",
    )


# ---------------------------------------------------------------------------
# GameSummary fixtures — mid-game
# ---------------------------------------------------------------------------

@pytest.fixture
def football_mid():
    return GameSummary(
        game_id="test-nfl-001",
        status="in",
        home_team="Green Bay Packers",
        away_team="Seattle Seahawks",
        home_score=14,
        away_score=10,
        home_record="10-4",
        away_record="8-6",
        period="Halftime",
        leaders=[
            {"name": "J. Love", "stat": "187 yds, 1 TD", "stat_name": "Passing", "team": "Green Bay Packers"},
            {"name": "A. Jones", "stat": "62 yds", "stat_name": "Rushing", "team": "Green Bay Packers"},
        ],
    )


@pytest.fixture
def basketball_mid():
    return GameSummary(
        game_id="test-nba-001",
        status="in",
        home_team="Los Angeles Lakers",
        away_team="Golden State Warriors",
        home_score=58,
        away_score=54,
        home_record="31-18",
        away_record="28-21",
        period="Halftime",
        leaders=[
            {"name": "A. Davis", "stat": "22 pts", "stat_name": "Points", "team": "Los Angeles Lakers"},
            {"name": "D. Green", "stat": "9 reb", "stat_name": "Rebounds", "team": "Golden State Warriors"},
            {"name": "L. James", "stat": "8 ast", "stat_name": "Assists", "team": "Los Angeles Lakers"},
        ],
    )


@pytest.fixture
def hockey_mid():
    return GameSummary(
        game_id="test-nhl-001",
        status="in",
        home_team="Los Angeles Kings",
        away_team="Seattle Kraken",
        home_score=2,
        away_score=1,
        home_record="34-22-6",
        away_record="29-28-5",
        period="End of 2nd",
        leaders=[
            {"name": "A. Kopitar", "stat": "1G, 1A", "stat_name": "Points", "team": "Los Angeles Kings"},
        ],
        goalie_saves={
            "Los Angeles Kings": {"name": "D. Rittich", "saves": "18"},
            "Seattle Kraken": {"name": "P. Grubauer", "saves": "16"},
        },
    )


@pytest.fixture
def baseball_mid():
    return GameSummary(
        game_id="test-mlb-001",
        status="in",
        home_team="Los Angeles Dodgers",
        away_team="Chicago Cubs",
        home_score=3,
        away_score=2,
        home_record="52-31",
        away_record="44-39",
        period="Middle 5th",
        leaders=[
            {"name": "S. Ohtani", "stat": "5 IP, 6 K, 1 ER", "stat_name": "Pitching", "team": "Los Angeles Dodgers"},
        ],
    )


# ---------------------------------------------------------------------------
# GameSummary fixtures — final
# ---------------------------------------------------------------------------

@pytest.fixture
def football_final_home_wins():
    return GameSummary(
        game_id="test-nfl-001",
        status="post",
        home_team="Green Bay Packers",
        away_team="Seattle Seahawks",
        home_score=27,
        away_score=24,
        home_record="11-4",
        away_record="8-7",
        period="Final",
        leaders=[
            {"name": "J. Love", "stat": "334 yds, 3 TD", "stat_name": "Passing", "team": "Green Bay Packers"},
            {"name": "G. Smith", "stat": "271 yds, 2 TD", "stat_name": "Passing", "team": "Seattle Seahawks"},
        ],
    )


@pytest.fixture
def football_final_away_wins():
    return GameSummary(
        game_id="test-nfl-002",
        status="post",
        home_team="Green Bay Packers",
        away_team="Seattle Seahawks",
        home_score=21,
        away_score=28,
        home_record="10-5",
        away_record="9-6",
        period="Final",
        leaders=[
            {"name": "G. Smith", "stat": "289 yds, 3 TD", "stat_name": "Passing", "team": "Seattle Seahawks"},
        ],
    )


# ---------------------------------------------------------------------------
# Odds / Weather fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_odds():
    return OddsResult(
        home_team="Green Bay Packers",
        away_team="Seattle Seahawks",
        home_spread="-3.0",
        away_spread="+3.0",
        total="45.5",
        home_ml="-155",
        away_ml="+130",
        bookmaker="FanDuel",
    )


@pytest.fixture
def sample_weather():
    return WeatherResult(
        temp_f=32.0,
        conditions="Light snow",
        wind_mph=12.5,
        precip_pct=60,
    )


# ---------------------------------------------------------------------------
# Soccer GameSummary fixtures
#
# ESPN pre-populates both half linescores from kickoff (both value=0), so
# linescore count can't be used for period detection. These fixtures mirror
# that real-world behaviour so the tests are realistic.
# ---------------------------------------------------------------------------

def _soccer_linescores(h1_home, h1_away, h2_home=0, h2_away=0, include_h2=True):
    """Helper: build ESPN-style linescore lists for a soccer game."""
    home = [{"displayValue": str(h1_home)}]
    away = [{"displayValue": str(h1_away)}]
    if include_h2:
        home.append({"displayValue": str(h2_home)})
        away.append({"displayValue": str(h2_away)})
    return home, away


@pytest.fixture
def soccer_in_progress_h1():
    """1st half in progress. ESPN pre-populates H2 linescore as "0"."""
    home_ls, away_ls = _soccer_linescores(0, 0)  # both halves pre-populated
    return GameSummary(
        game_id="test-soccer-001",
        status="in",
        status_name="STATUS_IN_PROGRESS",
        home_team="Argentina",
        away_team="France",
        home_score=0,
        away_score=0,
        home_record="",
        away_record="",
        period="1st Half",
        period_num=1,
        home_linescores=home_ls,
        away_linescores=away_ls,
    )


@pytest.fixture
def soccer_in_progress_h1_with_goal():
    """1st half in progress after a goal. ESPN updates H1 linescore; H2 stays at 0."""
    home_ls, away_ls = _soccer_linescores(h1_home=1, h1_away=0)
    return GameSummary(
        game_id="test-soccer-001",
        status="in",
        status_name="STATUS_IN_PROGRESS",
        home_team="Argentina",
        away_team="France",
        home_score=1,
        away_score=0,
        home_record="",
        away_record="",
        period="1st Half",
        period_num=1,
        home_linescores=home_ls,
        away_linescores=away_ls,
    )


@pytest.fixture
def soccer_halftime():
    """Regulation halftime — period 1 just ended, ESPN sets STATUS_HALFTIME."""
    home_ls, away_ls = _soccer_linescores(h1_home=1, h1_away=0)
    return GameSummary(
        game_id="test-soccer-001",
        status="in",
        status_name="STATUS_HALFTIME",
        home_team="Argentina",
        away_team="France",
        home_score=1,
        away_score=0,
        home_record="",
        away_record="",
        period="HT",
        period_num=1,
        home_linescores=home_ls,
        away_linescores=away_ls,
    )


@pytest.fixture
def soccer_in_progress_h2():
    """2nd half in progress."""
    home_ls, away_ls = _soccer_linescores(h1_home=1, h1_away=0)
    return GameSummary(
        game_id="test-soccer-001",
        status="in",
        status_name="STATUS_IN_PROGRESS",
        home_team="Argentina",
        away_team="France",
        home_score=1,
        away_score=0,
        home_record="",
        away_record="",
        period="2nd Half",
        period_num=2,
        home_linescores=home_ls,
        away_linescores=away_ls,
    )


@pytest.fixture
def soccer_full_time_going_to_et():
    """
    Regulation ends 1-1; game goes to extra time. ESPN signals the break
    with STATUS_HALFTIME at period_num=2 (not STATUS_FULL_TIME, which is
    only used when the game is truly over).
    """
    home_ls, away_ls = _soccer_linescores(h1_home=1, h1_away=0, h2_home=0, h2_away=1)
    return GameSummary(
        game_id="test-soccer-001",
        status="in",
        status_name="STATUS_HALFTIME",
        home_team="Argentina",
        away_team="France",
        home_score=1,
        away_score=1,
        home_record="",
        away_record="",
        period="HT ET",
        period_num=2,
        home_linescores=home_ls,
        away_linescores=away_ls,
    )


@pytest.fixture
def soccer_et_halftime():
    """Extra-time halftime — period 3 just ended, ESPN sets STATUS_HALFTIME."""
    home_ls = [
        {"displayValue": "1"},
        {"displayValue": "0"},
        {"displayValue": "1"},
        {"displayValue": "0"},
    ]
    away_ls = [
        {"displayValue": "0"},
        {"displayValue": "1"},
        {"displayValue": "0"},
        {"displayValue": "0"},
    ]
    return GameSummary(
        game_id="test-soccer-001",
        status="in",
        status_name="STATUS_HALFTIME",
        home_team="Argentina",
        away_team="France",
        home_score=2,
        away_score=1,
        home_record="",
        away_record="",
        period="HT ET",
        period_num=3,
        home_linescores=home_ls,
        away_linescores=away_ls,
    )


@pytest.fixture
def soccer_final_regulation():
    """Regular season game ends at full time (no extra time)."""
    home_ls, away_ls = _soccer_linescores(h1_home=1, h1_away=0, h2_home=1, h2_away=0)
    return GameSummary(
        game_id="test-soccer-001",
        status="post",
        status_name="STATUS_FULL_TIME",
        home_team="Argentina",
        away_team="France",
        home_score=2,
        away_score=0,
        home_record="",
        away_record="",
        period="Full Time",
        period_num=2,
        home_linescores=home_ls,
        away_linescores=away_ls,
    )


@pytest.fixture
def soccer_final_aet():
    """Knockout game ends after extra time."""
    home_ls = [
        {"displayValue": "1"},
        {"displayValue": "0"},
        {"displayValue": "1"},
        {"displayValue": "0"},
    ]
    away_ls = [
        {"displayValue": "0"},
        {"displayValue": "1"},
        {"displayValue": "0"},
        {"displayValue": "0"},
    ]
    return GameSummary(
        game_id="test-soccer-001",
        status="post",
        status_name="STATUS_FINAL_AET",
        home_team="Argentina",
        away_team="France",
        home_score=2,
        away_score=1,
        home_record="",
        away_record="",
        period="Final",
        period_num=4,
        home_linescores=home_ls,
        away_linescores=away_ls,
    )
