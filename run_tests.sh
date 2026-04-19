#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/gameday-bot"

echo "=== Gameday Bot — Test Runner ==="

# Check env
if [[ ! -f .env ]]; then
  echo "Warning: no .env file found — copy .env.example and fill in values"
fi

# Install deps if needed
if ! python3 -c "import slack_bolt" 2>/dev/null; then
  echo "Installing dependencies…"
  pip install -r requirements.txt
fi

echo ""
echo "--- 1. ESPN ID discovery (reads from cache or fetches live) ---"
python3 - <<'EOF'
import espn
ids = espn.discover_team_ids()
print(f"Resolved {len(ids)} team IDs:")
for name, eid in sorted(ids.items()):
    print(f"  {name}: {eid}")
EOF

echo ""
echo "--- 2. Today's schedule (dry run) ---"
DRY_RUN=true python3 - <<'EOF'
import os
os.environ.setdefault("DRY_RUN", "true")
import espn, config
from datetime import datetime, timezone

ids = espn.discover_team_ids()
today = datetime.now(timezone.utc).strftime("%Y%m%d")
team_ids = set(ids.values())

print(f"Fetching games for {today}…")
found = []
seen = set()
for team in config.TEAM_CONFIG:
    sport, league = team["sport"], team["league"]
    tid = ids.get(team["name"])
    if not tid:
        continue
    games = espn.get_games_for_date(sport, league, today, {tid})
    import time; time.sleep(0.5)
    for g in games:
        if g.game_id not in seen:
            seen.add(g.game_id)
            found.append(g)
            print(f"  {g.away_team} @ {g.home_team} — {g.start_time.strftime('%H:%M UTC')} [{sport}]")

if not found:
    print("  (no games today for configured teams)")
EOF

echo ""
echo "--- 3. Weather check (Seahawks home game location) ---"
python3 - <<'EOF'
import weather
from datetime import datetime, timezone
result = weather.get_game_weather("Seattle Seahawks", datetime.now(timezone.utc))
if result:
    print(f"  Lumen Field: {result.temp_f}°F, {result.conditions}, {result.wind_mph} mph wind")
else:
    print("  (no weather data returned — expected if coords missing)")
EOF

echo ""
echo "--- 4. Blurb generation (calls Claude API) ---"
if python3 -c "from dotenv import load_dotenv; load_dotenv(); import os; assert os.environ.get('ANTHROPIC_API_KEY', '')" 2>/dev/null; then
  python3 - <<'EOF'
import blurb
text = blurb.generate_blurb({
    "away_team": "Seattle Seahawks",
    "home_team": "Green Bay Packers",
    "sport": "football",
    "away_record": "8-5",
    "home_record": "9-4",
    "series_context": "Regular season",
    "injuries": "Geno Smith (questionable)",
})
print(f"  {text}")
EOF
else
  echo "  (skipped — ANTHROPIC_API_KEY not set)"
fi

echo ""
echo "--- 5. Pre-game dry-run post ---"
DRY_RUN=true python3 - <<'EOF'
import os
os.environ["DRY_RUN"] = "true"
# Reload config with DRY_RUN=true
import importlib, config
config.DRY_RUN = True

import slack_client
slack_client.DRY_RUN = True

from espn import Game
from datetime import datetime, timezone, timedelta
import formatter

game = Game(
    game_id="test-001",
    sport="football",
    league="nfl",
    home_team="Green Bay Packers",
    away_team="Seattle Seahawks",
    home_team_id="9",
    away_team_id="26",
    start_time=datetime.now(timezone.utc) + timedelta(hours=1),
    status="pre",
    broadcasts=["FOX", "NFL+"],
    series_context=None,
)

blocks = formatter.build_pregame_blocks(
    game=game,
    home_record="9-4",
    away_record="8-5",
    odds=None,
    weather=None,
    blurb="Lambeau hosts a must-watch NFC clash as Seattle looks to stay in playoff contention. Can Geno Smith silence the frozen tundra? Kickoff awaits.",
)

import json
print(json.dumps(blocks, indent=2))
EOF

echo ""
echo "=== All checks complete ==="
