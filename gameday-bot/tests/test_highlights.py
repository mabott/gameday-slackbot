from unittest.mock import MagicMock, patch

import pytest

import db
import formatter
import highlights
from highlights import HighlightState, _is_highlight_post, _team_matches, init_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post(
    title="[Highlight] Great dunk",
    domain="streamable.com",
    flair="Highlight",
    url="https://streamable.com/abc123",
    post_id="abc123",
    score=100,
    author="nba_fan",
):
    return {
        "id": post_id,
        "title": title,
        "domain": domain,
        "link_flair_text": flair,
        "url": url,
        "score": score,
        "author": author,
    }


def _lakers_state():
    return init_state("basketball", "Los Angeles Lakers", "Oklahoma City Thunder")


# ---------------------------------------------------------------------------
# _is_highlight_post
# ---------------------------------------------------------------------------

class TestIsHighlightPost:
    def test_streamable_with_flair(self):
        assert _is_highlight_post(_post(domain="streamable.com", flair="Highlight", title="Great play"))

    def test_streamable_with_bracket_title(self):
        assert _is_highlight_post(_post(domain="streamable.com", flair="", title="[Highlight] Great play"))

    def test_vredd_with_flair(self):
        assert _is_highlight_post(_post(domain="v.redd.it", flair="video", title="Some play"))

    def test_vredd_with_bracket(self):
        assert _is_highlight_post(_post(domain="v.redd.it", flair="", title="[Video] Nice pass"))

    def test_youtube_requires_both_flair_and_bracket(self):
        # only flair → rejected (podcast risk)
        assert not _is_highlight_post(_post(domain="youtube.com", flair="Highlight", title="NBA Podcast ep 12"))
        # only bracket → rejected
        assert not _is_highlight_post(_post(domain="youtube.com", flair="", title="[Highlight] Great play"))
        # both → accepted
        assert _is_highlight_post(_post(domain="youtube.com", flair="Highlight", title="[Highlight] Great play"))

    def test_youtu_be_also_strict(self):
        assert not _is_highlight_post(_post(domain="youtu.be", flair="Highlight", title="Podcast recap"))
        assert _is_highlight_post(_post(domain="youtu.be", flair="Highlight", title="[Highlight] Clutch shot"))

    def test_non_video_domain_always_rejected(self):
        assert not _is_highlight_post(_post(domain="reddit.com", flair="Highlight", title="[Highlight] Play"))
        assert not _is_highlight_post(_post(domain="twitter.com", flair="video", title="[Video] Clip"))

    def test_no_flair_no_bracket_rejected(self):
        assert not _is_highlight_post(_post(domain="streamable.com", flair="", title="Game thread"))

    def test_flair_case_insensitive(self):
        assert _is_highlight_post(_post(domain="streamable.com", flair="HIGHLIGHT", title="Play"))

    def test_bracket_case_insensitive(self):
        assert _is_highlight_post(_post(domain="streamable.com", flair="", title="[HIGHLIGHT] Big play"))

    def test_baseball_vredd_accepted_without_flair_or_bracket(self):
        # r/baseball posts plain v.redd.it clips with no flair or bracket
        assert _is_highlight_post(_post(domain="v.redd.it", flair="", title="Freeman crushes one to left"), subreddit="baseball")

    def test_baseball_vredd_still_rejected_for_other_subreddits(self):
        assert not _is_highlight_post(_post(domain="v.redd.it", flair="", title="Some plain clip"), subreddit="nba")

    def test_baseball_non_vredd_still_needs_flair_or_bracket(self):
        assert not _is_highlight_post(_post(domain="streamable.com", flair="", title="Freeman crushes one"), subreddit="baseball")
        assert _is_highlight_post(_post(domain="streamable.com", flair="", title="[Highlight] Freeman crushes one"), subreddit="baseball")

    def test_hockey_vredd_with_video_flair_accepted(self):
        # r/hockey uses "[Video]" flair (with brackets) on all goal clips
        assert _is_highlight_post(_post(domain="v.redd.it", flair="[Video]", title="[ANA 4 - VGK 3] Hertl gets one back"), subreddit="hockey")

    def test_hockey_vredd_without_video_flair_rejected(self):
        # Interviews and news also land on v.redd.it — require the flair
        assert not _is_highlight_post(_post(domain="v.redd.it", flair="", title="Player speaks to press"), subreddit="hockey")

    def test_hockey_video_flair_only_matches_hockey_subreddit(self):
        # "[Video]" flair should not unlock v.redd.it for other subreddits
        assert not _is_highlight_post(_post(domain="v.redd.it", flair="[Video]", title="Some play"), subreddit="nba")


# ---------------------------------------------------------------------------
# _team_matches
# ---------------------------------------------------------------------------

class TestTeamMatches:
    def setup_method(self):
        self.state = _lakers_state()

    def test_full_home_team_name_matches(self):
        assert _team_matches("Los Angeles Lakers highlights", self.state)

    def test_full_away_team_name_matches(self):
        assert _team_matches("Oklahoma City Thunder vs Lakers", self.state)

    def test_home_nickname_matches(self):
        assert _team_matches("Lakers dunk on Thunder", self.state)

    def test_away_nickname_matches(self):
        assert _team_matches("Thunder go up by 10", self.state)

    def test_no_match_returns_false(self):
        assert not _team_matches("Celtics beat the Heat", self.state)

    def test_case_insensitive(self):
        assert _team_matches("LAKERS WIN", self.state)
        assert _team_matches("thunder steal", self.state)


# ---------------------------------------------------------------------------
# init_state
# ---------------------------------------------------------------------------

def test_init_state_sets_subreddit():
    state = init_state("basketball", "Los Angeles Lakers", "Oklahoma City Thunder")
    assert state.subreddit == "nba"


def test_init_state_unknown_sport_defaults_to_sports():
    state = init_state("lacrosse", "Team A", "Team B")
    assert state.subreddit == "sports"


def test_init_state_extracts_nicknames():
    state = init_state("basketball", "Los Angeles Lakers", "Oklahoma City Thunder")
    assert state.home_nick == "Lakers"
    assert state.away_nick == "Thunder"


def test_init_state_seen_ids_empty():
    state = _lakers_state()
    assert state.seen_ids == set()


# ---------------------------------------------------------------------------
# scan_new_posts
# ---------------------------------------------------------------------------

REDDIT_RESPONSE = {
    "data": {
        "children": [
            {"data": _post(post_id="p1", title="[Highlight] Lakers dunk")},
            {"data": _post(post_id="p2", title="[Highlight] Thunder three-pointer")},
            {"data": _post(post_id="p3", title="Game discussion thread", flair="", domain="reddit.com")},
            {"data": _post(post_id="p4", title="[Highlight] Celtics beat Heat", domain="streamable.com", flair="")},
        ]
    }
}


def test_scan_new_posts_returns_matching_highlights():
    state = _lakers_state()
    with patch.object(highlights, "_reddit_get", return_value=REDDIT_RESPONSE):
        found = highlights.scan_new_posts(state)
    assert len(found) == 2
    ids = {p["id"] for p in found}
    assert ids == {"p1", "p2"}


def test_scan_new_posts_deduplicates_seen_ids():
    state = _lakers_state()
    state.seen_ids.add("p1")
    with patch.object(highlights, "_reddit_get", return_value=REDDIT_RESPONSE):
        found = highlights.scan_new_posts(state)
    assert all(p["id"] != "p1" for p in found)


def test_scan_new_posts_updates_seen_ids():
    state = _lakers_state()
    with patch.object(highlights, "_reddit_get", return_value=REDDIT_RESPONSE):
        highlights.scan_new_posts(state)
    assert "p1" in state.seen_ids
    assert "p2" in state.seen_ids


def test_scan_new_posts_returns_empty_on_api_failure():
    state = _lakers_state()
    with patch.object(highlights, "_reddit_get", return_value=None):
        found = highlights.scan_new_posts(state)
    assert found == []


# ---------------------------------------------------------------------------
# check_and_post
# ---------------------------------------------------------------------------

def test_check_and_post_skips_when_game_not_in_db(tmp_db):
    state = _lakers_state()
    with patch.object(highlights, "_reddit_get", return_value=REDDIT_RESPONSE):
        highlights.check_and_post("no-such-game", state)  # should not raise


def test_check_and_post_skips_when_no_slack_ts(tmp_db):
    db.upsert_game(
        game_id="g1", sport="basketball",
        home_team="Los Angeles Lakers", away_team="Oklahoma City Thunder",
        start_time_iso="2026-05-10T20:00:00+00:00", date="2026-05-10",
    )
    # slack_ts not set — post_reply should never be called
    state = _lakers_state()
    with patch.object(highlights, "_reddit_get", return_value=REDDIT_RESPONSE), \
         patch("slack_client.post_reply") as mock_reply:
        highlights.check_and_post("g1", state)
    mock_reply.assert_not_called()


def test_check_and_post_posts_each_highlight(tmp_db):
    db.upsert_game(
        game_id="g2", sport="basketball",
        home_team="Los Angeles Lakers", away_team="Oklahoma City Thunder",
        start_time_iso="2026-05-10T20:00:00+00:00", date="2026-05-10",
    )
    db.save_slack_ts("g2", "1234567890.123456")

    state = _lakers_state()
    with patch.object(highlights, "_reddit_get", return_value=REDDIT_RESPONSE), \
         patch("slack_client.post_reply") as mock_reply:
        highlights.check_and_post("g2", state)

    assert mock_reply.call_count == 2
    call_kwargs = [c.kwargs for c in mock_reply.call_args_list]
    assert all(k["thread_ts"] == "1234567890.123456" for k in call_kwargs)


def test_check_and_post_does_not_double_post(tmp_db):
    db.upsert_game(
        game_id="g3", sport="basketball",
        home_team="Los Angeles Lakers", away_team="Oklahoma City Thunder",
        start_time_iso="2026-05-10T20:00:00+00:00", date="2026-05-10",
    )
    db.save_slack_ts("g3", "1234567890.000000")

    state = _lakers_state()
    with patch.object(highlights, "_reddit_get", return_value=REDDIT_RESPONSE), \
         patch("slack_client.post_reply"):
        highlights.check_and_post("g3", state)
        # second call — same posts already in seen_ids
        call_count_before = len(state.seen_ids)
        highlights.check_and_post("g3", state)

    assert len(state.seen_ids) == call_count_before  # no new IDs added


# ---------------------------------------------------------------------------
# build_highlight_blocks (formatter)
# ---------------------------------------------------------------------------

def test_build_highlight_blocks_contains_title():
    post = _post(title="[Highlight] LeBron alley-oop", url="https://streamable.com/xyz", score=500, author="nba_clips")
    blocks = formatter.build_highlight_blocks(post)
    assert len(blocks) == 1
    text = blocks[0]["text"]["text"]
    assert "LeBron alley-oop" in text


def test_build_highlight_blocks_contains_url():
    post = _post(url="https://streamable.com/xyz")
    text = formatter.build_highlight_blocks(post)[0]["text"]["text"]
    assert "https://streamable.com/xyz" in text


def test_build_highlight_blocks_shows_upvotes_when_positive():
    post = _post(score=842, author="clipper")
    text = formatter.build_highlight_blocks(post)[0]["text"]["text"]
    assert "842" in text
    assert "upvotes" in text


def test_build_highlight_blocks_omits_upvotes_when_zero():
    post = _post(score=0)
    text = formatter.build_highlight_blocks(post)[0]["text"]["text"]
    assert "upvotes" not in text


def test_build_highlight_blocks_shows_author_and_domain():
    post = _post(author="nba_fan", domain="streamable.com")
    text = formatter.build_highlight_blocks(post)[0]["text"]["text"]
    assert "nba_fan" in text
    assert "streamable.com" in text
