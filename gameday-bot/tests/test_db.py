import db


def _insert(game_id="g001", date="2026-01-10"):
    db.upsert_game(
        game_id=game_id,
        sport="football",
        home_team="Green Bay Packers",
        away_team="Seattle Seahawks",
        start_time_iso="2026-01-10T20:00:00+00:00",
        date=date,
        home_record="10-4",
        away_record="8-6",
    )


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_db_creates_games_table(tmp_db):
    with db._conn() as conn:
        result = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='games'"
        ).fetchone()
    assert result is not None


def test_init_db_is_idempotent(tmp_db):
    db.init_db()
    db.init_db()


# ---------------------------------------------------------------------------
# upsert_game / get_game
# ---------------------------------------------------------------------------

def test_upsert_and_get_game_roundtrip(tmp_db):
    _insert("g001")
    row = db.get_game("g001")
    assert row is not None
    assert row["game_id"] == "g001"
    assert row["home_team"] == "Green Bay Packers"
    assert row["away_team"] == "Seattle Seahawks"
    assert row["sport"] == "football"
    assert row["home_record"] == "10-4"
    assert row["away_record"] == "8-6"


def test_upsert_stores_broadcasts(tmp_db):
    db.upsert_game(
        game_id="g001", sport="baseball", home_team="Los Angeles Dodgers",
        away_team="Chicago Cubs", start_time_iso="2026-05-01T19:10:00+00:00",
        date="2026-05-01", broadcasts="FS1,Apple TV+",
    )
    row = db.get_game("g001")
    assert row["broadcasts"] == "FS1,Apple TV+"


def test_broadcasts_parse_to_list(tmp_db):
    db.upsert_game(
        game_id="g001", sport="baseball", home_team="Los Angeles Dodgers",
        away_team="Chicago Cubs", start_time_iso="2026-05-01T19:10:00+00:00",
        date="2026-05-01", broadcasts="FS1,Apple TV+",
    )
    row = db.get_game("g001")
    parsed = [b for b in row.get("broadcasts", "").split(",") if b]
    assert parsed == ["FS1", "Apple TV+"]


def test_broadcasts_empty_string_parses_to_empty_list(tmp_db):
    db.upsert_game(
        game_id="g001", sport="baseball", home_team="Los Angeles Dodgers",
        away_team="Chicago Cubs", start_time_iso="2026-05-01T19:10:00+00:00",
        date="2026-05-01", broadcasts="",
    )
    row = db.get_game("g001")
    parsed = [b for b in row.get("broadcasts", "").split(",") if b]
    assert parsed == []


def test_upsert_updates_broadcasts_on_conflict(tmp_db):
    db.upsert_game(
        game_id="g001", sport="baseball", home_team="Los Angeles Dodgers",
        away_team="Chicago Cubs", start_time_iso="2026-05-01T19:10:00+00:00",
        date="2026-05-01", broadcasts="FS1",
    )
    db.upsert_game(
        game_id="g001", sport="baseball", home_team="Los Angeles Dodgers",
        away_team="Chicago Cubs", start_time_iso="2026-05-01T19:10:00+00:00",
        date="2026-05-01", broadcasts="ESPN,TNT",
    )
    assert db.get_game("g001")["broadcasts"] == "ESPN,TNT"


def test_upsert_updates_records_on_conflict(tmp_db):
    _insert("g001")
    db.upsert_game(
        game_id="g001",
        sport="football",
        home_team="Green Bay Packers",
        away_team="Seattle Seahawks",
        start_time_iso="2026-01-10T20:00:00+00:00",
        date="2026-01-10",
        home_record="11-4",
        away_record="9-6",
    )
    row = db.get_game("g001")
    assert row["home_record"] == "11-4"
    assert row["away_record"] == "9-6"


def test_upsert_no_duplicate_on_conflict(tmp_db):
    _insert("g001")
    _insert("g001")
    with db._conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM games WHERE game_id = 'g001'"
        ).fetchone()[0]
    assert count == 1


def test_get_game_returns_none_for_missing(tmp_db):
    assert db.get_game("does-not-exist") is None


# ---------------------------------------------------------------------------
# is_posted / mark_posted
# ---------------------------------------------------------------------------

def test_is_posted_all_false_before_any_mark(tmp_db):
    _insert("g001")
    assert not db.is_posted("g001", "pregame")
    assert not db.is_posted("g001", "midgame")
    assert not db.is_posted("g001", "final")


def test_mark_and_is_posted_pregame(tmp_db):
    _insert("g001")
    db.mark_posted("g001", "pregame")
    assert db.is_posted("g001", "pregame")


def test_mark_and_is_posted_midgame(tmp_db):
    _insert("g001")
    db.mark_posted("g001", "midgame")
    assert db.is_posted("g001", "midgame")


def test_mark_and_is_posted_final(tmp_db):
    _insert("g001")
    db.mark_posted("g001", "final")
    assert db.is_posted("g001", "final")


def test_marking_one_stage_does_not_affect_others(tmp_db):
    _insert("g001")
    db.mark_posted("g001", "pregame")
    assert db.is_posted("g001", "pregame")
    assert not db.is_posted("g001", "midgame")
    assert not db.is_posted("g001", "final")


def test_is_posted_false_for_unknown_game(tmp_db):
    assert not db.is_posted("no-such-game", "pregame")


# ---------------------------------------------------------------------------
# save_slack_ts
# ---------------------------------------------------------------------------

def test_save_slack_ts_persisted(tmp_db):
    _insert("g001")
    db.save_slack_ts("g001", "1712345678.000100")
    assert db.get_game("g001")["slack_ts"] == "1712345678.000100"


# ---------------------------------------------------------------------------
# get_games_for_date
# ---------------------------------------------------------------------------

def test_get_games_for_date_returns_matching_games(tmp_db):
    _insert("g001", date="2026-01-10")
    _insert("g002", date="2026-01-10")
    ids = {g["game_id"] for g in db.get_games_for_date("2026-01-10")}
    assert ids == {"g001", "g002"}


def test_get_games_for_date_excludes_other_dates(tmp_db):
    _insert("g001", date="2026-01-10")
    _insert("g002", date="2026-01-11")
    ids = {g["game_id"] for g in db.get_games_for_date("2026-01-10")}
    assert "g002" not in ids


# ---------------------------------------------------------------------------
# cleanup_old_games
# ---------------------------------------------------------------------------

def test_cleanup_removes_games_before_cutoff(tmp_db):
    _insert("g001", date="2026-01-09")
    db.cleanup_old_games(before_date="2026-01-10")
    assert db.get_game("g001") is None


def test_cleanup_keeps_games_on_cutoff_date(tmp_db):
    _insert("g001", date="2026-01-10")
    db.cleanup_old_games(before_date="2026-01-10")
    assert db.get_game("g001") is not None


def test_cleanup_keeps_games_after_cutoff(tmp_db):
    _insert("g001", date="2026-01-11")
    db.cleanup_old_games(before_date="2026-01-10")
    assert db.get_game("g001") is not None
