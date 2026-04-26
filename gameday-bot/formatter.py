from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import SPORT_EMOJIS, TZ


def _pacific(dt: datetime) -> str:
    tz = ZoneInfo(TZ)
    local = dt.astimezone(tz)
    return local.strftime("%-I:%M %p %Z")


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _divider() -> dict:
    return {"type": "divider"}


def _header(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def build_pregame_blocks(game) -> list[dict]:
    emoji = SPORT_EMOJIS.get(game.sport, "🏟️")
    parts = [f"{emoji} GAME DAY: {game.away_team} @ {game.home_team}",
             _pacific(game.start_time)]
    if game.venue:
        parts.append(game.venue)
    if game.broadcasts:
        parts.append(", ".join(game.broadcasts))
    return [_header(" · ".join(parts))]


def build_pregame_thread_blocks(
    game,
    home_record: str,
    away_record: str,
    odds=None,
    weather=None,
    blurb: str = "",
) -> list[dict]:
    lines = [
        f"• *Records:* {game.away_team} ({away_record}) vs {game.home_team} ({home_record})",
    ]

    if odds:
        away_line = f"{game.away_team} {odds.away_spread}"
        home_line = f"{game.home_team} {odds.home_spread}"
        lines.append(f"• *Spread:* {away_line} | {home_line} | O/U {odds.total}  _{odds.bookmaker}_")

    if game.series_context:
        lines.append(f"• *Series:* {game.series_context}")

    if weather:
        lines.append(
            f"• *Weather:* {weather.temp_f}°F, {weather.conditions}, "
            f"{weather.wind_mph} mph wind, {weather.precip_pct}% precip"
        )

    blocks = [_section("\n".join(lines))]

    if blurb:
        blocks.append(_divider())
        blocks.append(_section(blurb))

    return blocks


def build_midgame_blocks(summary, sport: str) -> list[dict]:
    emoji = SPORT_EMOJIS.get(sport, "🏟️")
    period_label = _period_label(sport, summary.period)

    blocks = [
        _header(f"🔄 {period_label} UPDATE"),
        _section(
            f"*Score:* {summary.away_team} *{summary.away_score}* — "
            f"{summary.home_team} *{summary.home_score}*"
        ),
    ]

    stat_line = _build_stat_line(summary, sport)
    if stat_line:
        blocks.append(_section(stat_line))

    return blocks


def build_final_blocks(summary, sport: str) -> list[dict]:
    if summary.home_score > summary.away_score:
        winner = summary.home_team
    else:
        winner = summary.away_team

    verb = "win" if winner.rstrip("!").endswith("s") else "wins"

    blocks = [
        _header(
            f"🏁 FINAL: {summary.away_team} {summary.away_score} — "
            f"{summary.home_team} {summary.home_score}"
        ),
        _section(f"*{winner} {verb}!*"),
    ]

    performers = _build_top_performers(summary, sport)
    if performers:
        blocks.append(_divider())
        blocks.append(_section("*Top performers:*\n" + performers))

    if summary.series_context:
        blocks.append(_divider())
        blocks.append(_section(f"🏆 *Series:* {summary.series_context}"))

    return blocks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sport_time_label(sport: str) -> str:
    return {
        "football": "Kickoff",
        "basketball": "Tip-off",
        "baseball": "First pitch",
        "hockey": "Puck drop",
    }.get(sport, "Start")


def _period_label(sport: str, period_text: str) -> str:
    if sport == "football":
        return "HALFTIME"
    if sport == "basketball":
        return "HALFTIME"
    if sport == "hockey":
        return "END OF 2ND PERIOD"
    if sport == "baseball":
        return f"MID-GAME ({period_text})"
    return "MID-GAME"


def _build_stat_line(summary, sport: str) -> str:
    leaders = summary.leaders
    if not leaders:
        return ""

    if sport == "basketball":
        pts = [l for l in leaders if "Points" in l.get("stat_name", "")][:1]
        reb = [l for l in leaders if "Rebound" in l.get("stat_name", "")][:1]
        ast = [l for l in leaders if "Assist" in l.get("stat_name", "")][:1]
        parts = []
        for l in pts:
            parts.append(f"Points leader: {l['name']} ({l['stat']})")
        for l in reb:
            parts.append(f"Reb: {l['name']} ({l['stat']})")
        for l in ast:
            parts.append(f"Ast: {l['name']} ({l['stat']})")
        return " | ".join(parts)

    if sport == "hockey":
        lines = []
        for l in leaders[:3]:
            lines.append(f"{l['name']} — {l['stat_name']}: {l['stat']}")
        saves_parts = []
        for team, g in summary.goalie_saves.items():
            saves_parts.append(f"{g['name']} ({team}): {g['saves']} saves")
        if saves_parts:
            lines.append("Goalies: " + ", ".join(saves_parts))
        return "\n".join(lines)

    if sport == "football":
        parts = []
        for l in leaders[:3]:
            parts.append(f"{l['name']} — {l['stat_name']}: {l['stat']}")
        return "\n".join(parts)

    if sport == "baseball":
        parts = []
        for l in leaders[:3]:
            parts.append(f"{l['name']} — {l['stat_name']}: {l['stat']}")
        return "\n".join(parts)

    return ""


def _build_top_performers(summary, sport: str) -> str:
    leaders = summary.leaders
    if not leaders:
        return ""

    lines = []
    if sport == "basketball":
        pts = [l for l in leaders if "Points" in l.get("stat_name", "")][:1]
        reb = [l for l in leaders if "Rebound" in l.get("stat_name", "")][:1]
        ast = [l for l in leaders if "Assist" in l.get("stat_name", "")][:1]
        for l in pts + reb + ast:
            lines.append(f"• {l['name']}: {l['stat']} {l['stat_name'].lower()}")

    elif sport == "hockey":
        for l in leaders[:4]:
            lines.append(f"• {l['name']}: {l['stat']} {l['stat_name'].lower()}")
        for team, g in summary.goalie_saves.items():
            lines.append(f"• {g['name']} (G): {g['saves']} saves")

    elif sport == "football":
        for l in leaders[:4]:
            lines.append(f"• {l['name']}: {l['stat']} {l['stat_name'].lower()}")

    elif sport == "baseball":
        for l in leaders[:4]:
            lines.append(f"• {l['name']}: {l['stat']} {l['stat_name'].lower()}")

    return "\n".join(lines)
