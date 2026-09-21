import json

import app.db
from app.engines.night_compare import compare_day_night
from app.engines.tariff_breakdown import calc_fare

T = {"start_price": 11, "start_include_km": 3, "per_km": 2.5, "per_slow_min": 0.8, "night_factor": 1.2}

EXPECTED_DELTA = 11.62

def test_day_short():
    r = calc_fare(5, 2, False, T)
    assert r["total"] == 17.6
    assert r["mileage"] == 5.0

def test_night_long():
    r = calc_fare(18, 12, True, T)
    assert r["total"] == 69.72

def test_compare_delta():
    c = compare_day_night(18, 12, T)
    assert c["day_total"] == 58.1
    assert c["night_total"] == 69.72
    assert c["delta"] == EXPECTED_DELTA, f"delta={c['delta']} expected={EXPECTED_DELTA}"
    assert c["delta"] == round(c["night_total"] - c["day_total"], 2), (
        f"delta={c['delta']} expected=night_total-day_total="
        f"{round(c['night_total'] - c['day_total'], 2)}"
    )
    for key in ("start", "mileage", "slow_fee"):
        expect = round(c["day"][key] * T["night_factor"], 2)
        assert c["night"][key] == expect, f"{key}: night={c['night'][key]} expected={expect}"

def _compare_count(conn):
    return conn.execute("SELECT COUNT(*) c FROM calc_runs WHERE kind='compare'").fetchone()["c"]

def test_compare_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(app.db, "DB_PATH", tmp_path / "iso.db")
    from app.seed import init_db
    from app.services.taxi_service import TaxiService

    init_db()
    conn = app.db.connect()
    with TaxiService() as s:
        n0 = _compare_count(conn)
        s.compare(18, 12, False)
        assert _compare_count(conn) == n0
        r = s.compare(18, 12, True)
        assert _compare_count(conn) == n0 + 1
        assert r["delta"] == EXPECTED_DELTA, f"delta={r['delta']} expected={EXPECTED_DELTA}"
        row = conn.execute(
            "SELECT kind, result_json FROM calc_runs WHERE kind='compare' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row["kind"] == "compare"
        saved = json.loads(row["result_json"])
        assert saved["delta"] == EXPECTED_DELTA, f"persisted delta={saved['delta']} expected={EXPECTED_DELTA}"
    conn.close()
