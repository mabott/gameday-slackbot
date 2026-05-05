import logging
import time
from dataclasses import replace
from typing import Optional

import espn
import db
import formatter
import slack_client

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300  # 5 minutes
MAX_POLLS = 36               # give up after 3 hours of polling

HALFTIME_MAX_POLLS = 20      # give up waiting for halftime after ~30-40 minutes


def _sleep_for_clock(clock_secs: float) -> int:
    """
    Estimate real-world sleep time from NBA game clock seconds.

    NBA clocks stop constantly — fouls, timeouts, made baskets. The last
    2 minutes of a quarter routinely take 15+ real minutes, so we apply a
    larger multiplier there. Values are clamped to [60, 600] seconds.
    """
    if clock_secs <= 0:
        return 60  # clock at 0:00 but halftime not yet confirmed — check soon
    if clock_secs <= 120:
        return max(60, min(int(clock_secs * 4), 480))
    return max(60, min(int(clock_secs * 2), 600))


def poll_for_halftime(game_id: str, sport: str, league: str) -> Optional[espn.GameSummary]:
    """
    Poll ESPN until Q2 ends, then return a summary with the actual halftime
    scores taken from play-by-play data. Uses the game clock to pace polls.
    Falls back to the most recent live summary if polling times out.
    """
    log.info("Polling for basketball halftime: game %s", game_id)
    summary = None

    for attempt in range(HALFTIME_MAX_POLLS):
        summary = espn.get_game_summary(sport, league, game_id)
        if not summary:
            time.sleep(120)
            continue

        at_halftime = summary.period_num >= 3 or "half" in summary.period.lower()
        if at_halftime:
            log.info("Halftime confirmed for %s after %d poll(s)", game_id, attempt + 1)
            ht = espn.basketball_halftime_scores(summary.plays)
            if ht:
                summary = replace(summary, away_score=ht[0], home_score=ht[1])
            return summary

        sleep_secs = _sleep_for_clock(summary.clock_secs)
        log.debug(
            "Game %s: Q%d, %s (%.0fs on clock) — sleeping %ds",
            game_id, summary.period_num, summary.period, summary.clock_secs, sleep_secs,
        )
        time.sleep(sleep_secs)

    log.warning(
        "Halftime poll timed out for %s after %d attempts, using live score",
        game_id, HALFTIME_MAX_POLLS,
    )
    return summary


def poll_for_final(game_id: str, sport: str, league: str):
    """
    Polls ESPN until the game status is final, then posts the final recap.
    Intended to be called in a background thread/job after expected game duration.
    """
    if db.is_posted(game_id, "final"):
        log.info("Final already posted for %s, skipping poll", game_id)
        return

    log.info("Starting post-game poll for game %s (%s/%s)", game_id, sport, league)

    for attempt in range(MAX_POLLS):
        summary = espn.get_game_summary(sport, league, game_id)

        if summary and summary.status == "post":
            log.info("Game %s is final after %d polls", game_id, attempt + 1)
            _post_final(game_id, summary, sport)
            return

        log.debug("Game %s not final yet (attempt %d/%d)", game_id, attempt + 1, MAX_POLLS)
        time.sleep(POLL_INTERVAL_SECONDS)

    log.warning("Gave up polling for final on game %s after %d attempts", game_id, MAX_POLLS)


def _post_final(game_id: str, summary, sport: str):
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
