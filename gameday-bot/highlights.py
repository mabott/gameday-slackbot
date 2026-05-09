"""
highlights.py — Reddit highlight detection for in-game Slack posts.

Polls r/<subreddit>/new for posts with Highlight flair that mention
the teams playing. Intended to be called each iteration of the in-game
poller via check_and_post().

Run standalone for testing:
    python highlights.py --sport basketball --home "Oklahoma City Thunder" \
        --away "Los Angeles Lakers" --date 2026-05-07
"""

import argparse
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

import db
import formatter
import slack_client

log = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({"User-Agent": "gameday-bot/1.0 (highlight scanner)"})

SUBREDDITS = {
    "basketball": "nba",
    "football": "nfl",
    "baseball": "baseball",
    "hockey": "hockey",
}

HIGHLIGHT_FLAIRS = {"highlight", "video", "highlights"}

HIGHLIGHT_KEYWORDS = {"[highlight]", "[highlights]", "[video]"}

HIGHLIGHT_DOMAINS = {
    "streamable.com",
    "v.redd.it",
    "youtube.com",
    "youtu.be",
    "gfycat.com",
    "clips.twitch.tv",
}

REDDIT_BASE = "https://www.reddit.com"


@dataclass
class HighlightState:
    subreddit: str
    home_team: str
    away_team: str
    home_nick: str        # last word, e.g. "Thunder"
    away_nick: str        # last word, e.g. "Lakers"
    seen_ids: set = field(default_factory=set)
    game_thread_id: Optional[str] = None


def init_state(sport: str, home_team: str, away_team: str) -> HighlightState:
    subreddit = SUBREDDITS.get(sport, "sports")
    return HighlightState(
        subreddit=subreddit,
        home_team=home_team,
        away_team=away_team,
        home_nick=home_team.split()[-1],
        away_nick=away_team.split()[-1],
    )


def _reddit_get(path: str, params: dict = None, retries: int = 3) -> Optional[dict]:
    url = f"{REDDIT_BASE}{path}"
    for attempt in range(retries):
        try:
            resp = _session.get(url, params=params, timeout=10)
            if resp.status_code == 429:
                log.warning("Reddit rate limit hit, sleeping 10s")
                time.sleep(10)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            log.warning("Reddit request failed (attempt %d/%d): %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def _team_matches(title: str, state: HighlightState) -> bool:
    """True if the title references either team by full name or nickname."""
    t = title.lower()
    return (
        state.home_team.lower() in t or
        state.away_team.lower() in t or
        state.home_nick.lower() in t or
        state.away_nick.lower() in t
    )


def _is_highlight_post(post: dict) -> bool:
    """
    True if this Reddit post looks like a game highlight clip.

    Domain alone is not sufficient — podcasts and talk shows also post to
    streamable/YouTube. We require the post to also carry a Highlight flair
    OR have [Highlight]/[Video] brackets in the title. YouTube links are held
    to the stricter standard of requiring *both*, since podcasts live there too.
    """
    flair = (post.get("link_flair_text") or "").lower()
    title_lower = post.get("title", "").lower()
    domain = post.get("domain", "").lower()

    flair_match = flair in HIGHLIGHT_FLAIRS
    bracket_match = any(kw in title_lower for kw in HIGHLIGHT_KEYWORDS)
    is_video_domain = any(dom in domain for dom in HIGHLIGHT_DOMAINS)

    if not is_video_domain:
        return False

    is_youtube = "youtube.com" in domain or "youtu.be" in domain
    if is_youtube:
        return flair_match and bracket_match  # both required — podcasts won't have [Highlight]

    return flair_match or bracket_match  # streamable/v.redd.it: either is enough


def find_game_thread(subreddit: str, home_team: str, away_team: str) -> Optional[str]:
    """
    Search for the [Game Thread] post on Reddit. Returns the post ID or None.
    Used to confirm the game is live; highlights are found via scan_new_posts().
    """
    home_nick = home_team.split()[-1]
    away_nick = away_team.split()[-1]
    query = f"flair:\"Game Thread\" {home_nick} {away_nick}"
    data = _reddit_get(
        f"/r/{subreddit}/search.json",
        params={"q": query, "sort": "new", "t": "week", "restrict_sr": "1", "limit": 5},
    )
    if not data:
        return None

    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        flair = (d.get("link_flair_text") or "").lower()
        if flair == "game thread":
            post_id = d.get("id")
            log.info("Found game thread for %s vs %s: %s", away_nick, home_nick, post_id)
            return post_id

    log.warning("No game thread found for %s vs %s", away_nick, home_nick)
    return None


def scan_new_posts(state: HighlightState) -> list[dict]:
    """
    Fetch /r/<subreddit>/new and return highlight posts for this game
    that haven't been seen before. Updates state.seen_ids in place.
    """
    data = _reddit_get(f"/r/{state.subreddit}/new.json", params={"limit": 100})
    if not data:
        return []

    found = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        post_id = post.get("id", "")
        if post_id in state.seen_ids:
            continue
        if not _is_highlight_post(post):
            continue
        if not _team_matches(post.get("title", ""), state):
            continue
        state.seen_ids.add(post_id)
        found.append(post)
        log.info("New highlight: [%s] %s", post.get("domain", ""), post.get("title", "")[:80])

    return found


def check_and_post(game_id: str, state: HighlightState):
    """
    Scan for new highlights and post each one as a thread reply.
    Called each iteration of poll_in_game_updates().
    """
    row = db.get_game(game_id)
    if not row:
        return
    thread_ts = row.get("slack_ts")
    if not thread_ts:
        return

    new_highlights = scan_new_posts(state)
    for post in new_highlights:
        blocks = formatter.build_highlight_blocks(post)
        title = post.get("title", "")
        url = post.get("url", "")
        text = f"Highlight: {title}"
        slack_client.post_reply(blocks=blocks, text=text, thread_ts=thread_ts)
        log.info("Highlight posted for game %s: %s", game_id, title[:60])


# ---------------------------------------------------------------------------
# CLI for testing — no Slack, just print what would be posted
# ---------------------------------------------------------------------------

def _run_test(sport: str, home_team: str, away_team: str, date: str):
    subreddit = SUBREDDITS.get(sport, "sports")
    state = init_state(sport, home_team, away_team)

    print(f"\nSearching r/{subreddit} for: {away_team} @ {home_team} ({date})")
    print("=" * 70)

    game_thread_id = find_game_thread(subreddit, home_team, away_team)
    if game_thread_id:
        print(f"Game thread found: https://reddit.com/r/{subreddit}/comments/{game_thread_id}")
    else:
        print("No game thread found (may be too old or not posted yet)")

    print(f"\nScanning r/{subreddit}/new for highlights...")
    highlights = scan_new_posts(state)

    # Also try a targeted search for older games
    if not highlights:
        print("None in /new — trying date-scoped search...")
        home_nick = home_team.split()[-1]
        away_nick = away_team.split()[-1]
        data = _reddit_get(
            f"/r/{subreddit}/search.json",
            params={
                "q": f"flair:Highlight {home_nick} {away_nick}",
                "sort": "new", "t": "week",
                "restrict_sr": "1", "limit": 25,
            },
        )
        if data:
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                if post.get("id") not in state.seen_ids:
                    state.seen_ids.add(post["id"])
                    highlights.append(post)

    print(f"\nFound {len(highlights)} highlights:\n")
    for post in highlights:
        ts = datetime.fromtimestamp(post.get("created", 0), tz=timezone.utc)
        score = post.get("score", 0)
        domain = post.get("domain", "")
        title = post.get("title", "")
        url = post.get("url", "")
        print(f"  [{ts.strftime('%H:%M UTC')}] score={score:>5}  {domain}")
        print(f"    {title[:90]}")
        print(f"    {url}")
        print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser(description="Test Reddit highlight detection")
    parser.add_argument("--sport", default="basketball")
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()
    _run_test(args.sport, args.home, args.away, args.date)
