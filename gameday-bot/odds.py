import logging
from dataclasses import dataclass
from typing import Optional

import requests

from config import ODDS_API_KEY, ODDS_SPORT_KEYS

log = logging.getLogger(__name__)

ODDS_BASE = "https://api.the-odds-api.com/v4/sports"
PREFERRED_BOOKS = ["fanduel", "draftkings"]


@dataclass
class OddsResult:
    home_team: str
    away_team: str
    home_spread: str
    away_spread: str
    total: str
    home_ml: str
    away_ml: str
    bookmaker: str


def _fuzzy_match(config_name: str, odds_name: str) -> bool:
    cn_words = set(config_name.lower().split())
    on_words = set(odds_name.lower().split())
    return bool(cn_words & on_words)


def get_odds(sport_path: str, home_team: str, away_team: str) -> Optional[OddsResult]:
    if not ODDS_API_KEY:
        log.debug("ODDS_API_KEY not set, skipping odds fetch")
        return None

    sport_key = ODDS_SPORT_KEYS.get(sport_path)
    if not sport_key:
        log.warning("No odds sport key for path %s", sport_path)
        return None

    try:
        resp = requests.get(
            f"{ODDS_BASE}/{sport_key}/odds/",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "spreads,h2h,totals",
                "bookmakers": ",".join(PREFERRED_BOOKS),
            },
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Odds API request failed: %s", exc)
        return None

    games = resp.json()
    for game in games:
        gh = game.get("home_team", "")
        ga = game.get("away_team", "")
        if not (_fuzzy_match(home_team, gh) and _fuzzy_match(away_team, ga)):
            continue

        # Find best available bookmaker
        bookmakers = game.get("bookmakers", [])
        book = next(
            (b for b in bookmakers if b["key"] in PREFERRED_BOOKS),
            bookmakers[0] if bookmakers else None,
        )
        if not book:
            continue

        markets = {m["key"]: m for m in book.get("markets", [])}
        spread_market = markets.get("spreads", {})
        h2h_market = markets.get("h2h", {})
        totals_market = markets.get("totals", {})

        def outcome_for(market, team_name):
            for o in market.get("outcomes", []):
                if _fuzzy_match(team_name, o.get("name", "")):
                    return o
            return {}

        home_spread_o = outcome_for(spread_market, gh)
        away_spread_o = outcome_for(spread_market, ga)
        home_ml_o = outcome_for(h2h_market, gh)
        away_ml_o = outcome_for(h2h_market, ga)
        total_o = totals_market.get("outcomes", [{}])[0]

        def fmt_spread(o):
            pt = o.get("point", "")
            if pt == "":
                return "N/A"
            return f"+{pt}" if float(pt) > 0 else str(pt)

        def fmt_ml(o):
            price = o.get("price", "")
            if price == "":
                return "N/A"
            return f"+{int(price)}" if float(price) > 0 else str(int(price))

        return OddsResult(
            home_team=gh,
            away_team=ga,
            home_spread=fmt_spread(home_spread_o),
            away_spread=fmt_spread(away_spread_o),
            total=str(total_o.get("point", "N/A")),
            home_ml=fmt_ml(home_ml_o),
            away_ml=fmt_ml(away_ml_o),
            bookmaker=book.get("title", ""),
        )

    log.debug("No odds match found for %s @ %s", away_team, home_team)
    return None
