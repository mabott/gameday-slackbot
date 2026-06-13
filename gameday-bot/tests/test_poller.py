"""
Tests for poller._detect_period_end, with focus on soccer.

Soccer-specific regression: ESPN pre-populates both half linescores with
value=0 from kickoff, so the linescore-count approach used for other sports
fires halftime and full-time alerts immediately. The fix uses STATUS_HALFTIME
from summary.status_name instead.
"""
import pytest

from poller import _detect_period_end


# ---------------------------------------------------------------------------
# Soccer — regression cases for the linescore pre-population bug
# ---------------------------------------------------------------------------

def test_soccer_no_trigger_during_first_half(soccer_in_progress_h1):
    """STATUS_IN_PROGRESS with pre-populated H2 linescore must not fire."""
    result = _detect_period_end(soccer_in_progress_h1, "soccer", last_period_posted=0)
    assert result is None


def test_soccer_no_trigger_after_goal_in_first_half(soccer_in_progress_h1_with_goal):
    """Scoring a goal updates the linescore but must not fire a period-end post."""
    result = _detect_period_end(soccer_in_progress_h1_with_goal, "soccer", last_period_posted=0)
    assert result is None


def test_soccer_no_trigger_during_second_half(soccer_in_progress_h2):
    """STATUS_IN_PROGRESS in the 2nd half must not trigger (halftime already posted)."""
    result = _detect_period_end(soccer_in_progress_h2, "soccer", last_period_posted=1)
    assert result is None


# ---------------------------------------------------------------------------
# Soccer — correct trigger cases
# ---------------------------------------------------------------------------

def test_soccer_halftime_fires_at_status_halftime(soccer_halftime):
    """STATUS_HALFTIME at period 1 must fire exactly once."""
    result = _detect_period_end(soccer_halftime, "soccer", last_period_posted=0)
    assert result is not None
    period, scores = result
    assert period == 1


def test_soccer_halftime_not_repeated(soccer_halftime):
    """STATUS_HALFTIME must not re-fire if we already posted period 1."""
    result = _detect_period_end(soccer_halftime, "soccer", last_period_posted=1)
    assert result is None


def test_soccer_ft_et_break_fires_at_period_2(soccer_full_time_going_to_et):
    """
    Knockout game: regulation ends 1-1, ESPN signals the break with
    STATUS_HALFTIME at period_num=2. Should post the FULL TIME period update.
    """
    result = _detect_period_end(soccer_full_time_going_to_et, "soccer", last_period_posted=1)
    assert result is not None
    period, scores = result
    assert period == 2


def test_soccer_ft_et_break_not_repeated(soccer_full_time_going_to_et):
    """The FT→ET break post must not re-fire after period 2 is recorded."""
    result = _detect_period_end(soccer_full_time_going_to_et, "soccer", last_period_posted=2)
    assert result is None


def test_soccer_et_halftime_fires_at_period_3(soccer_et_halftime):
    """Extra-time halftime at period 3 should fire after periods 1 and 2 posted."""
    result = _detect_period_end(soccer_et_halftime, "soccer", last_period_posted=2)
    assert result is not None
    period, scores = result
    assert period == 3


def test_soccer_et_halftime_not_repeated(soccer_et_halftime):
    result = _detect_period_end(soccer_et_halftime, "soccer", last_period_posted=3)
    assert result is None


# ---------------------------------------------------------------------------
# Soccer — period scores at halftime are correct
# ---------------------------------------------------------------------------

def test_soccer_halftime_scores(soccer_halftime):
    """Period scores at halftime should reflect actual H1 score, not pre-populated 0."""
    _, scores = _detect_period_end(soccer_halftime, "soccer", last_period_posted=0)
    # H1: France 0 — Argentina 1  (away=France, home=Argentina)
    away_cum, home_cum = scores[1]
    assert home_cum == 1
    assert away_cum == 0


def test_soccer_ft_et_break_scores(soccer_full_time_going_to_et):
    """Period scores at the FT→ET break should show H1 and H2 correctly."""
    _, scores = _detect_period_end(soccer_full_time_going_to_et, "soccer", last_period_posted=1)
    # H1: home 1, away 0 → cumulative after H1: home=1, away=0
    # H2: home 0, away 1 → cumulative after H2: home=1, away=1
    away_h1, home_h1 = scores[1]
    away_h2, home_h2 = scores[2]
    assert home_h1 == 1 and away_h1 == 0
    assert home_h2 == 1 and away_h2 == 1


# ---------------------------------------------------------------------------
# Soccer — final states must not trigger period-end (handled by _post_final)
# ---------------------------------------------------------------------------

def test_soccer_final_regulation_no_period_trigger(soccer_final_regulation):
    """STATUS_FULL_TIME has status='post'; period detection must return None."""
    result = _detect_period_end(soccer_final_regulation, "soccer", last_period_posted=1)
    assert result is None


def test_soccer_final_aet_no_period_trigger(soccer_final_aet):
    """STATUS_FINAL_AET has status='post'; period detection must return None."""
    result = _detect_period_end(soccer_final_aet, "soccer", last_period_posted=3)
    assert result is None


# ---------------------------------------------------------------------------
# Non-soccer sports unaffected — quick sanity checks
# ---------------------------------------------------------------------------

def test_basketball_linescore_approach_unchanged(basketball_mid):
    """Basketball still uses linescore count; verify the path is untouched."""
    basketball_mid.home_linescores = [{"value": 28}, {"value": 30}]
    basketball_mid.away_linescores = [{"value": 27}, {"value": 27}]
    result = _detect_period_end(basketball_mid, "basketball", last_period_posted=1)
    assert result is not None
    period, _ = result
    assert period == 2


def test_hockey_linescore_approach_unchanged(hockey_mid):
    """Hockey still uses linescore count."""
    hockey_mid.home_linescores = [{"value": 1}, {"value": 1}]
    hockey_mid.away_linescores = [{"value": 0}, {"value": 1}]
    result = _detect_period_end(hockey_mid, "hockey", last_period_posted=1)
    assert result is not None
    period, _ = result
    assert period == 2
