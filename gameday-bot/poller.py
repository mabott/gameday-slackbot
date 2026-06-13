import logging
import threading
import time
from typing import Optional

import espn
import db
import formatter
import slack_client

log = logging.getLogger(__name__)

_stop = threading.Event()


def request_stop():
    """Signal all running pollers to exit at their next sleep boundary."""
    _stop.set()


MAX_IN_GAME_POLLS = 72  # 72 × 5 min average = ~6 hrs before giving up

# Fixed sleep (seconds) for sports where clock-based pacing doesn't apply.
# Basketball and football use _sleep_for_clock() instead.
_FIXED_SLEEP = {
    "hockey": 60,
    "baseball": 180,
    "soccer": 60,
}


def _sleep_for_clock(clock_secs: float) -> int:
    """
    Estimate real-world sleep from NBA/NFL game clock seconds.

    The last 2 minutes of a quarter routinely take 15+ real minutes due to
    constant stoppages, so we apply a larger multiplier there.
    Clamped to [60, 600] seconds.
    """
    if clock_secs <= 0:
        return 60
    if clock_secs <= 120:
        return max(60, min(int(clock_secs * 4), 480))
    return max(60, min(int(clock_secs * 2), 600))


def poll_in_game_updates(game_id: str, sport: str, league: str):
    """
    Poll ESPN from game start through final, posting:
      - Period/quarter/inning-end summaries with linescore and stat leaders
      - Hockey goal alerts whenever the score changes between polls
      - Final recap when the game ends

    Replaces the old separate midgame and final poller jobs.
    """
    if db.is_posted(game_id, "final"):
        log.info("Final already posted for %s, skipping in-game poll", game_id)
        return

    log.info("Starting in-game poller for %s (%s/%s)", game_id, sport, league)

    last_period_posted = 0
    last_score_total = 0    # hockey/soccer: detect score changes between polls
    last_play_index = 0     # hockey: scan position in plays list
    last_key_event_index = 0  # soccer: scan position in keyEvents list
    last_bottom_inning = 0  # baseball: last inning where bottom half was observed

    for attempt in range(MAX_IN_GAME_POLLS):
        if _stop.is_set():
            log.info("Poller for %s stopping due to shutdown signal", game_id)
            return

        summary = espn.get_game_summary(sport, league, game_id)
        if not summary:
            if _stop.wait(timeout=60):
                log.info("Poller for %s stopping due to shutdown signal", game_id)
                return
            continue

        # --- Hockey: goal alert on score change ---
        if sport == "hockey":
            current_total = summary.home_score + summary.away_score
            if current_total > last_score_total:
                goal = espn.last_goal_from_plays(summary.plays, last_play_index)
                if goal:
                    last_play_index = goal["play_index"] + 1
                    _post_goal_alert(game_id, summary, goal["scorer"], goal["team"])
                last_score_total = current_total

        # --- Soccer: goal alert on score change via keyEvents ---
        if sport == "soccer":
            current_total = summary.home_score + summary.away_score
            if current_total > last_score_total:
                idx = last_key_event_index
                while True:
                    goal = espn.last_goal_from_keyevents(summary.key_events, idx)
                    if not goal:
                        break
                    idx = goal["event_index"] + 1
                    _post_goal_alert(
                        game_id, summary, goal["scorer"], goal["team"],
                        clock=goal["clock"], description=goal["description"],
                    )
                last_key_event_index = idx
                last_score_total = current_total

        # --- Baseball: record each bottom half we observe ---
        if sport == "baseball" and "bot" in summary.period.lower():
            last_bottom_inning = max(last_bottom_inning, summary.period_num)

        # --- Period/quarter/inning end detection ---
        result = _detect_period_end(summary, sport, last_period_posted, last_bottom_inning)
        if result is not None:
            completed_period, period_scores = result
            _post_period_end(game_id, summary, sport, completed_period, period_scores)
            last_period_posted = completed_period

        # --- Game over ---
        if summary.status == "post":
            log.info("Game %s is final after %d poll(s)", game_id, attempt + 1)
            _post_final(game_id, summary, sport)
            return

        # --- Sleep (interruptible so shutdown doesn't hang) ---
        fixed = _FIXED_SLEEP.get(sport)
        sleep_secs = fixed if fixed else _sleep_for_clock(summary.clock_secs)
        if _stop.wait(timeout=sleep_secs):
            log.info("Poller for %s stopping due to shutdown signal", game_id)
            return

    log.warning("In-game poller timed out for %s after %d attempts", game_id, MAX_IN_GAME_POLLS)


def _period_scores_from_linescores(home_ls: list, away_ls: list) -> dict:
    """
    Convert ESPN per-period linescores into the cumulative format expected by
    _build_linescore: {period_num: (cumulative_away, cumulative_home)}.
    Soccer linescores use displayValue (string); other sports use value (number).
    """
    result = {}
    home_cum = away_cum = 0
    for i, (h, a) in enumerate(zip(home_ls, away_ls), start=1):
        hv = h.get("value") if h.get("value") is not None else h.get("displayValue", 0)
        av = a.get("value") if a.get("value") is not None else a.get("displayValue", 0)
        home_cum += int(hv or 0)
        away_cum += int(av or 0)
        result[i] = (away_cum, home_cum)
    return result


def _detect_period_end(
    summary, sport: str, last_period_posted: int, last_bottom_inning: int = 0
) -> Optional[tuple]:
    """
    Returns (completed_period_num, period_scores) when a new period has ended,
    otherwise None. Posts one period at a time to handle catch-up correctly.

    Baseball uses plays (period_scores from plays buffer) because inning timing
    is tracked separately via last_bottom_inning.

    Basketball/football/hockey use ESPN header linescores instead of plays —
    linescores accumulate reliably for all completed periods throughout the game,
    whereas the plays buffer only contains recent plays and scrolls off.
    """
    if sport == "baseball":
        period_scores = espn.scores_by_period(summary.plays)
        if last_bottom_inning > last_period_posted:
            current = summary.period.lower()
            # Trigger when no longer in the bottom of the inning we recorded
            past_bottom = "bot" not in current or summary.period_num > last_bottom_inning
            if past_bottom and last_bottom_inning in period_scores:
                return last_bottom_inning, period_scores
        return None

    # Basketball, football, hockey: use linescores from ESPN header.
    # len(home_linescores) == number of completed periods, so we can detect
    # period end without relying on the plays buffer.
    period_scores = _period_scores_from_linescores(
        summary.home_linescores, summary.away_linescores
    )
    next_to_post = last_period_posted + 1
    if len(summary.home_linescores) >= next_to_post and next_to_post in period_scores:
        return next_to_post, period_scores

    return None


def _post_period_end(game_id: str, summary, sport: str, period_num: int, period_scores: dict):
    row = db.get_game(game_id)
    if not row:
        log.error("Game %s not in DB for period-end post", game_id)
        return
    thread_ts = row.get("slack_ts")
    if not thread_ts:
        log.warning("No slack_ts for %s — pre-game may have failed; skipping period-end post", game_id)
        return

    blocks = formatter.build_period_end_blocks(summary, sport, period_num, period_scores)
    label = formatter._period_end_label(sport, period_num)
    text = f"{label}: {summary.away_team} {summary.away_score} — {summary.home_team} {summary.home_score}"
    slack_client.post_reply(blocks=blocks, text=text, thread_ts=thread_ts)
    log.info("Period %d end posted for %s", period_num, game_id)


def _post_goal_alert(
    game_id: str, summary, scorer_name: str, scorer_team: str,
    clock: str = "", description: str = "",
):
    row = db.get_game(game_id)
    if not row:
        return
    thread_ts = row.get("slack_ts")
    if not thread_ts:
        return

    blocks = formatter.build_goal_alert_blocks(
        summary, scorer_name, scorer_team, clock=clock, description=description
    )
    text = f"Goal — {scorer_team}: {scorer_name}"
    if clock:
        text += f" ({clock})"
    slack_client.post_reply(blocks=blocks, text=text, thread_ts=thread_ts)
    log.info("Goal alert posted for %s (scorer: %s)", game_id, scorer_name)


def _post_final(game_id: str, summary, sport: str):
    if db.is_posted(game_id, "final"):
        log.info("Final already posted for %s", game_id)
        return

    row = db.get_game(game_id)
    if not row:
        log.error("Game %s not found in DB, cannot post final", game_id)
        return
    thread_ts = row.get("slack_ts")
    if not thread_ts:
        log.error("No slack_ts for game %s, cannot post final in thread", game_id)
        return

    blocks = formatter.build_final_blocks(summary, sport)
    text = f"Final: {summary.away_team} {summary.away_score} — {summary.home_team} {summary.home_score}"
    ok = slack_client.post_reply(blocks=blocks, text=text, thread_ts=thread_ts)
    if ok:
        db.mark_posted(game_id, "final")
        log.info("Final recap posted for game %s", game_id)
