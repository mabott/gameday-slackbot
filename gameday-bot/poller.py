import logging
import time

import espn
import db
import formatter
import slack_client

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300  # 5 minutes
MAX_POLLS = 36               # give up after 3 hours of polling


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
