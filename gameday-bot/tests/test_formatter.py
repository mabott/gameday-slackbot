from dataclasses import replace

import pytest

import formatter
from espn import GameSummary


# ---------------------------------------------------------------------------
# build_pregame_blocks
# ---------------------------------------------------------------------------

def test_pregame_blocks_single_header(football_game):
    blocks = formatter.build_pregame_blocks(football_game)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "header"


def test_pregame_blocks_sport_emojis(football_game, basketball_game, hockey_game, baseball_game):
    for game, expected_emoji in [
        (football_game, "🏈"),
        (basketball_game, "🏀"),
        (hockey_game, "🏒"),
        (baseball_game, "⚾"),
    ]:
        text = formatter.build_pregame_blocks(game)[0]["text"]["text"]
        assert expected_emoji in text


def test_pregame_blocks_team_names(football_game):
    text = formatter.build_pregame_blocks(football_game)[0]["text"]["text"]
    assert "Green Bay Packers" in text
    assert "Seattle Seahawks" in text


def test_pregame_blocks_venue_present(football_game):
    text = formatter.build_pregame_blocks(football_game)[0]["text"]["text"]
    assert "Lambeau Field" in text


def test_pregame_blocks_venue_omitted_when_empty(football_game):
    text = formatter.build_pregame_blocks(replace(football_game, venue=""))[0]["text"]["text"]
    assert "Lambeau Field" not in text


def test_pregame_blocks_broadcasts_present(football_game):
    text = formatter.build_pregame_blocks(football_game)[0]["text"]["text"]
    assert "FOX" in text
    assert "NFL+" in text


def test_pregame_blocks_broadcasts_omitted_when_empty(football_game):
    text = formatter.build_pregame_blocks(replace(football_game, broadcasts=[]))[0]["text"]["text"]
    assert "FOX" not in text


# ---------------------------------------------------------------------------
# build_pregame_thread_blocks
# ---------------------------------------------------------------------------

def test_thread_blocks_records_line(football_game):
    blocks = formatter.build_pregame_thread_blocks(
        game=football_game, home_record="10-4", away_record="8-6"
    )
    assert len(blocks) == 1
    text = blocks[0]["text"]["text"]
    assert "Records" in text
    assert "10-4" in text
    assert "8-6" in text


def test_thread_blocks_series_context_replaces_records(football_game):
    game = replace(football_game, series_context="Packers lead series 2-1")
    blocks = formatter.build_pregame_thread_blocks(
        game=game, home_record="10-4", away_record="8-6"
    )
    text = blocks[0]["text"]["text"]
    assert "Series" in text
    assert "2-1" in text
    assert "Records" not in text


def test_thread_blocks_odds_present(football_game, sample_odds):
    blocks = formatter.build_pregame_thread_blocks(
        game=football_game, home_record="10-4", away_record="8-6", odds=sample_odds
    )
    text = blocks[0]["text"]["text"]
    assert "Spread" in text
    assert "-3.0" in text
    assert "+3.0" in text
    assert "45.5" in text
    assert "FanDuel" in text


def test_thread_blocks_odds_omitted_when_none(football_game):
    blocks = formatter.build_pregame_thread_blocks(
        game=football_game, home_record="10-4", away_record="8-6", odds=None
    )
    assert "Spread" not in blocks[0]["text"]["text"]


def test_thread_blocks_weather_present(football_game, sample_weather):
    blocks = formatter.build_pregame_thread_blocks(
        game=football_game, home_record="10-4", away_record="8-6", weather=sample_weather
    )
    text = blocks[0]["text"]["text"]
    assert "Weather" in text
    assert "32.0" in text
    assert "Light snow" in text
    assert "12.5" in text


def test_thread_blocks_weather_omitted_when_none(football_game):
    blocks = formatter.build_pregame_thread_blocks(
        game=football_game, home_record="10-4", away_record="8-6", weather=None
    )
    assert "Weather" not in blocks[0]["text"]["text"]


def test_thread_blocks_blurb_adds_divider_and_section(football_game):
    blocks = formatter.build_pregame_thread_blocks(
        game=football_game, home_record="10-4", away_record="8-6",
        blurb="Big game tonight at Lambeau.",
    )
    assert len(blocks) == 3
    assert blocks[1]["type"] == "divider"
    assert blocks[2]["text"]["text"] == "Big game tonight at Lambeau."


def test_thread_blocks_no_blurb_single_block(football_game):
    blocks = formatter.build_pregame_thread_blocks(
        game=football_game, home_record="10-4", away_record="8-6", blurb=""
    )
    assert len(blocks) == 1


# ---------------------------------------------------------------------------
# build_midgame_blocks
# ---------------------------------------------------------------------------

def test_midgame_football_halftime_label(football_mid):
    header_text = formatter.build_midgame_blocks(football_mid, "football")[0]["text"]["text"]
    assert "HALFTIME" in header_text


def test_midgame_basketball_halftime_label(basketball_mid):
    header_text = formatter.build_midgame_blocks(basketball_mid, "basketball")[0]["text"]["text"]
    assert "HALFTIME" in header_text


def test_midgame_hockey_period_label(hockey_mid):
    header_text = formatter.build_midgame_blocks(hockey_mid, "hockey")[0]["text"]["text"]
    assert "END OF 2ND PERIOD" in header_text


def test_midgame_baseball_period_label(baseball_mid):
    header_text = formatter.build_midgame_blocks(baseball_mid, "baseball")[0]["text"]["text"]
    assert "MID-GAME" in header_text


def test_midgame_score_line_contains_teams_and_scores(football_mid):
    blocks = formatter.build_midgame_blocks(football_mid, "football")
    score_text = blocks[1]["text"]["text"]
    assert "Green Bay Packers" in score_text
    assert "Seattle Seahawks" in score_text
    assert "14" in score_text
    assert "10" in score_text


def test_midgame_hockey_goalie_saves_in_stat_block(hockey_mid):
    blocks = formatter.build_midgame_blocks(hockey_mid, "hockey")
    all_section_text = " ".join(
        b["text"]["text"] for b in blocks if b["type"] == "section"
    )
    assert "saves" in all_section_text.lower()


# ---------------------------------------------------------------------------
# build_final_blocks
# ---------------------------------------------------------------------------

def test_final_home_team_wins(football_final_home_wins):
    blocks = formatter.build_final_blocks(football_final_home_wins, "football")
    winner_text = blocks[1]["text"]["text"]
    assert "Green Bay Packers" in winner_text


def test_final_away_team_wins(football_final_away_wins):
    blocks = formatter.build_final_blocks(football_final_away_wins, "football")
    winner_text = blocks[1]["text"]["text"]
    assert "Seattle Seahawks" in winner_text


def test_final_verb_plural_team():
    # Team name ending in 's' → "win"
    summary = GameSummary(
        game_id="x", status="post",
        home_team="Green Bay Packers", away_team="Seattle Seahawks",
        home_score=27, away_score=24,
        home_record="", away_record="", period="Final",
    )
    winner_text = formatter.build_final_blocks(summary, "football")[1]["text"]["text"]
    assert "Packers win!" in winner_text


def test_final_verb_non_plural_team():
    # Team name not ending in 's' → "wins"
    summary = GameSummary(
        game_id="x", status="post",
        home_team="Utah Jazz", away_team="Chicago Bulls",
        home_score=110, away_score=105,
        home_record="", away_record="", period="Final",
    )
    winner_text = formatter.build_final_blocks(summary, "basketball")[1]["text"]["text"]
    assert "Jazz wins!" in winner_text


def test_final_no_performers_section_when_no_leaders():
    summary = GameSummary(
        game_id="x", status="post",
        home_team="Green Bay Packers", away_team="Seattle Seahawks",
        home_score=27, away_score=24,
        home_record="", away_record="", period="Final",
        leaders=[],
    )
    blocks = formatter.build_final_blocks(summary, "football")
    all_section_text = " ".join(
        b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"
    )
    assert "Top performers" not in all_section_text


def test_final_series_context_block_present(football_final_home_wins):
    summary = replace(football_final_home_wins, series_context="Packers lead series 3-1")
    blocks = formatter.build_final_blocks(summary, "football")
    all_section_text = " ".join(
        b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"
    )
    assert "Series" in all_section_text
    assert "3-1" in all_section_text


def test_final_no_series_block_when_none(football_final_home_wins):
    blocks = formatter.build_final_blocks(football_final_home_wins, "football")
    all_section_text = " ".join(
        b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"
    )
    assert "Series" not in all_section_text
