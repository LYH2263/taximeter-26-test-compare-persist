import json

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import db
from app.engines.night_compare import compare_day_night
from app.engines.tariff_breakdown import calc_fare
from app.main import app

T = {"start_price": 11, "start_include_km": 3, "per_km": 2.5, "per_slow_min": 0.8, "night_factor": 1.2}

EXPECTED_DAY = 58.1
EXPECTED_NIGHT = 69.72
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

    assert c["day_total"] == EXPECTED_DAY, (
        f"白天车费不符：得到 {c['day_total']!r}，期望 {EXPECTED_DAY!r}"
    )
    assert c["night_total"] == EXPECTED_NIGHT, (
        f"夜间车费不符：得到 {c['night_total']!r}，期望 {EXPECTED_NIGHT!r}"
    )
    assert c["delta"] == EXPECTED_DELTA, (
        f"差值不符：得到 {c['delta']!r}，期望 {EXPECTED_DELTA!r}"
    )
    # 差值必须精确等于夜间减白天（四舍五入到分），不得用大小比较代替
    assert c["delta"] == round(c["night_total"] - c["day_total"], 2), (
        f"差值不等于夜间减白天：差值 {c['delta']!r}，"
        f"夜间减白天 {round(c['night_total'] - c['day_total'], 2)!r}"
    )

    # 白天三项：起步 11、里程 37.5、等候 9.6
    assert c["day"]["start"] == 11.0
    assert c["day"]["mileage"] == 37.5
    assert c["day"]["slow_fee"] == 9.6
    # 夜间三项须分别等于白天对应项乘 1.2 再四舍五入到分
    expected_night_parts = {"start": 13.2, "mileage": 45.0, "slow_fee": 11.52}
    for key, expected_value in expected_night_parts.items():
        day_value = c["day"][key]
        scaled = round(day_value * T["night_factor"], 2)
        night_value = c["night"][key]
        assert night_value == scaled, (
            f"夜间{key}不等于白天对应项乘 1.2 后四舍五入到分："
            f"得到 {night_value!r}，期望 {scaled!r}（白天 {day_value!r} × 1.2）"
        )
        assert night_value == expected_value, (
            f"夜间{key}金额不符：得到 {night_value!r}，期望 {expected_value!r}"
        )


@pytest.fixture
def isolated_client(tmp_path, monkeypatch):
    """每个用例使用独立的临时 SQLite 库，不触碰默认数据目录。"""
    db_path = tmp_path / "isolated_app.db"
    monkeypatch.setattr(app_config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    with TestClient(app) as client:
        yield client


def _compare_rows():
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM calc_runs WHERE kind = 'compare' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def test_compare_entry_no_persist_adds_no_record(isolated_client):
    assert _compare_rows() == []

    resp = isolated_client.post(
        "/api/compare", json={"distance_km": 18, "slow_min": 12, "persist": False}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] is None
    assert data["day_total"] == EXPECTED_DAY
    assert data["night_total"] == EXPECTED_NIGHT
    assert data["delta"] == EXPECTED_DELTA, (
        f"差值不符：得到 {data['delta']!r}，期望 {EXPECTED_DELTA!r}"
    )

    rows = _compare_rows()
    assert rows == [], f"persist 为假时不应写入 compare 记录，实际得到 {len(rows)} 条"


def test_compare_entry_persist_adds_one_compare_record(isolated_client):
    assert _compare_rows() == []

    resp = isolated_client.post(
        "/api/compare", json={"distance_km": 18, "slow_min": 12, "persist": True}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] is not None
    assert data["delta"] == EXPECTED_DELTA, (
        f"差值不符：得到 {data['delta']!r}，期望 {EXPECTED_DELTA!r}"
    )

    rows = _compare_rows()
    assert len(rows) == 1, f"persist 为真时应恰好写入 1 条 compare 记录，实际得到 {len(rows)} 条"
    row = rows[0]
    assert row["kind"] == "compare"

    stored = json.loads(row["result_json"])
    assert stored["delta"] == EXPECTED_DELTA, (
        f"入库差值不符：得到 {stored.get('delta')!r}，期望 {EXPECTED_DELTA!r}"
    )
    assert stored["day_total"] == EXPECTED_DAY
    assert stored["night_total"] == EXPECTED_NIGHT
