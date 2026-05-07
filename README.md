# Gameday Slackbot

Posts game day threads to a Slack channel for a configured set of sports teams. Each game gets one top-level message ~60 minutes before tip-off, a mid-game update at halftime/intermission, and a final recap once the game ends — all threaded to keep the channel clean.

Supports NFL, NBA, MLB, and NHL. Teams are configured in `teams.yaml` — no code changes required to add or remove teams.

---

## Setup

### 1. Create a virtual environment

From the repo root:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r gameday-bot/requirements.txt
```

### 2. Create your `.env`

```bash
cp gameday-bot/.env.example gameday-bot/.env
```

Then fill in the values (see API Keys below).

### 3. Configure your teams

```bash
cp gameday-bot/teams.yaml.example gameday-bot/teams.yaml
```

Edit `teams.yaml` to add or remove teams. Each entry needs a `name`, `sport`, and `league`. NFL and MLB teams playing in outdoor stadiums should also include `stadium_coords` for weather data. See the example file for the full format.

Teams with identical nicknames in different leagues (Kings, Giants, Cardinals, etc.) are safe — the bot matches each team within its own sport/league bucket.

### 4. SSL certificates (macOS only)

If you installed Python from python.org, run this once:

```bash
open /Applications/Python\ 3.11/Install\ Certificates.command
```

---

## API Keys

### Slack (`SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`)

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Under **OAuth & Permissions** → **Bot Token Scopes**, add `chat:write` and `chat:write.public`
3. Click **Install to Workspace** → copy the **Bot User OAuth Token** (`xoxb-...`)
4. Get your channel ID from the Slack URL: `https://app.slack.com/client/T.../C0123ABC456` — it's the part starting with `C`

### Anthropic (`ANTHROPIC_API_KEY`)

Sign in at [console.anthropic.com](https://console.anthropic.com) → **API Keys** → **Create Key** (`sk-ant-...`)

### The Odds API (`ODDS_API_KEY`) — optional

Register for a free key (500 req/month) at [the-odds-api.com](https://the-odds-api.com). Leave blank to omit odds from posts.

### Enabling Claude blurbs (`BLURB_ENABLED`)

Setting `ANTHROPIC_API_KEY` alone is not enough — blurbs are off by default to avoid unexpected API charges. Set `BLURB_ENABLED=true` in `.env` to turn them on:

```env
ANTHROPIC_API_KEY=sk-ant-...
BLURB_ENABLED=true
```

---

## Running

### Production

```bash
cd gameday-bot && python3 bot.py
```

On startup the bot discovers ESPN team IDs, loads today's schedule, and schedules all pre/mid/final posts automatically. A daily refresh runs at 6:00 AM to pick up the next day's games.

### Dry run (no Slack posts)

Prints Block Kit JSON to stdout instead of posting:

```bash
cd gameday-bot && DRY_RUN=true python3 bot.py
```

### Test post

Fire all three posts immediately without waiting for a real game:

```bash
cd gameday-bot && python3 test_post.py                             # synthetic game
cd gameday-bot && python3 test_post.py --team "Dodgers"            # next real Dodgers game
cd gameday-bot && python3 test_post.py --team "Dodgers" --historical  # most recent completed Dodgers game
cd gameday-bot && python3 test_post.py --stage pre                 # pre-game only
cd gameday-bot && python3 test_post.py --delay 10                  # 10s between posts
```

`DRY_RUN=true` works with `test_post.py` too.

### Force ESPN ID cache refresh

If team IDs look stale or a new team was added, force re-discovery and exit:

```bash
cd gameday-bot && python3 bot.py --refresh-ids
```

### Test runner

Validates ESPN discovery, schedule fetching, weather, blurb generation, and Block Kit formatting:

```bash
./run_tests.sh
```

---

## Project structure

```
gameday-bot/
├── bot.py              # Entry point and scheduler
├── config.py           # Loads teams.yaml, env vars, sport constants
├── teams.yaml          # Your team list (gitignored, copy from .example)
├── teams.yaml.example  # Template
├── db.py               # SQLite state (deduplication, thread ts)
├── espn.py             # ESPN API + team ID auto-discovery
├── odds.py             # The Odds API (spreads, moneyline)
├── weather.py          # Open-Meteo (outdoor NFL/MLB only)
├── blurb.py            # Claude-generated preview blurb
├── formatter.py        # Slack Block Kit message builder
├── slack_client.py     # Slack posting + dry-run support
├── scheduler.py        # Job scheduling logic
├── poller.py           # Post-game polling loop
├── test_post.py        # Manual test fire tool
└── requirements.txt
```
