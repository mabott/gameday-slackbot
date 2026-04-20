import logging

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def generate_blurb(game_meta: dict) -> str:
    """
    game_meta keys: away_team, home_team, sport, away_record, home_record,
                    series_context (optional), injuries (optional)
    Returns a 2-3 sentence preview blurb, or empty string on failure.
    """
    try:
        prompt = (
            "Generate a 2-3 sentence game day preview blurb for a sports Slack channel. "
            "Be punchy and fan-friendly. No fluff, but a bit of snark is welcome. "
            "Focus on the most interesting storyline.\n\n"
            f"Game: {game_meta['away_team']} @ {game_meta['home_team']}\n"
            f"Sport: {game_meta['sport']}\n"
            f"Records: {game_meta.get('away_record', 'N/A')} vs {game_meta.get('home_record', 'N/A')}\n"
            f"Context: {game_meta.get('series_context', 'Regular season')}\n"
            f"Key injuries: {game_meta.get('injuries', 'None reported')}"
        )
        response = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        log.warning("Blurb generation failed: %s", exc)
        return ""
