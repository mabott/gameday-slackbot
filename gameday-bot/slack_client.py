import json
import logging
from typing import Optional

from slack_bolt import App

from config import SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, DRY_RUN

log = logging.getLogger(__name__)

app = App(token=SLACK_BOT_TOKEN) if not DRY_RUN else None


def _dry_run_print(label: str, blocks: list, text: str, thread_ts: Optional[str] = None):
    print(f"\n{'='*60}")
    print(f"DRY RUN — {label}")
    if thread_ts:
        print(f"thread_ts: {thread_ts}")
    print(f"fallback text: {text}")
    print("blocks:")
    print(json.dumps(blocks, indent=2))
    print("=" * 60)


def post_message(blocks: list, text: str) -> Optional[str]:
    """Post a new top-level message. Returns ts on success."""
    if DRY_RUN:
        _dry_run_print("POST MESSAGE", blocks, text)
        return "dry-run-ts-000"

    try:
        result = app.client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            blocks=blocks,
            text=text,
        )
        ts = result["ts"]
        log.info("Posted message ts=%s", ts)
        return ts
    except Exception as exc:
        log.error("Failed to post message: %s", exc)
        return None


def post_reply(blocks: list, text: str, thread_ts: str) -> bool:
    """Post a reply in a thread."""
    if DRY_RUN:
        _dry_run_print("POST REPLY", blocks, text, thread_ts)
        return True

    try:
        app.client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            thread_ts=thread_ts,
            blocks=blocks,
            text=text,
        )
        log.info("Posted reply in thread ts=%s", thread_ts)
        return True
    except Exception as exc:
        log.error("Failed to post reply in thread %s: %s", thread_ts, exc)
        return False
