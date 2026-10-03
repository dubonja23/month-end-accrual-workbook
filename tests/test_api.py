"""API: every tab's data comes from these endpoints; edits recalculate through them."""
import pytest

from accrual_workbook.api import create_app
from accrual_workbook.runner import DEFAULT_CONFIG

P = "2026-09"


@pytest.fixture
def client(sample_dir, tmp_path):
    app = create_app(sample_dir, DEFAULT_CONFIG, tmp_path / "api.db", tmp_path / "user")
    return app.test_client()


def get_period(client):
    r = client.get(f"/api/period/{P}")
    assert r.status_code == 200
    return r.get_json()


def line(data, key):
    return next(ln for ln in data["vendor_opex"]["lines"] if ln["key"] == key)


def test_meta_and_index(client):
    meta = client.get("/api/meta").get_json()
    assert meta["company"] == "Sample Co." and meta["current_period"] == P
    assert meta["periods"][0] == P
    assert client.get("/").status_code == 200


def test_period_payload_has_every_tab(client):
    d = get_period(client)
    for k in ("totals", "components", "checklist", "scope", "vendor_opex", "standing", "legal", "capex", "je",
              "mom", "over_budget", "budget", "posting_vs_service", "gl_detail", "attention_items"):
        assert k in d, k
    assert d["totals"]["total"] == 403591.51
    assert len(d["attention_items"]) >= 3


def test_override_recalculates_and_validates(client):
    r = client.post(f"/api/period/{P}/override", json={"key": "V1001|60200", "amount": "-5", "explanation": "x"})
    assert r.status_code == 400 and "negative" in r.get_json()["error"]
    r = client.post(f"/api/period/{P}/override", json={"key": "V1001|60200", "amount": "1000",
                                                         "explanation": "Vendor estimate for Sep"})
    assert r.status_code == 200
    d = get_period(client)
    assert line(d, "V1001|60200")["final_accrual"] == 1000.0
    assert d["totals"]["total"] == 404591.51
    assert all(c["ok"] for c in d["je"]["checks"])
    log = client.get(f"/api/period/{P}/override-log?key=V1001|60200").get_json()
    assert log[0]["action"] == "set"


def test_manual_add_and_delete(client):
    r = client.post(f"/api/period/{P}/manual", json={"vendor": "Lumen Kite Studio", "vendor_id": "V5001",
                                                       "gl_account": "64200", "amount": "1500", "dept": "D400",
                                                       "location": "L10", "item": "I-MKT",
                                                       "explanation": "Offsite booking deposit"})
    assert r.status_code == 200
    d = get_period(client)
    assert line(d, "V5001|64200")["final_accrual"] == 1500.0
    client.delete(f"/api/period/{P}/manual/{r.get_json()['id']}")
    assert all(ln["key"] != "V5001|64200" for ln in get_period(client)["vendor_opex"]["lines"])
    r = client.post("/api/period/2026-08/manual", json={"vendor": "X", "vendor_id": "V5002", "gl_account": "64200",
                                                       "amount": "1", "dept": "D", "location": "L", "item": "I",
                                                       "explanation": "Old month"})
    assert r.status_code == 400  # current period only


def test_legal_split_through_api(client):
    r = client.post(f"/api/period/{P}/legal/V2001", json={"fields": {}, "splits": [
        {"amount": "30000", "gl": "61500", "item": "I-LEGAL", "note": "General"},
        {"amount": "12500", "gl": "61600", "item": "I-LEGAL", "note": "Litigation"}]})
    assert r.status_code == 200
    d = get_period(client)
    assert d["legal"]["total"] == 88550.0
    assert sum(1 for ln in d["je"]["lines"] if ln["section"] == "Legal" and ln["side"] == "debit") == 4


def test_downloads(client):
    r = client.get(f"/api/period/{P}/je.csv")
    assert r.status_code == 200 and r.data.startswith(b"JOURNAL,DATE")
    r = client.get(f"/api/period/{P}/backup.xlsx")
    assert r.status_code == 200 and r.data[:2] == b"PK"


def test_signoff_blocked_then_locked(client):
    assert client.post(f"/api/period/{P}/signoff").status_code == 409
    d = get_period(client)
    for item in d["attention_items"]:
        client.patch(f"/api/period/{P}/attention/{item['id']}", json={"status": "Resolved", "resolution": "Done"})
    for row in d["mom"]["rows"]:
        if row["large_swing"]:
            client.post(f"/api/period/{P}/mom/review", json={"key": row["key"], "reviewed": True})
    for t in d["standing"]["table"]:
        if t["needs_confirm"]:
            client.post(f"/api/period/{P}/standing/confirm", json={"key": t["key"]})
    for c in ("vendor_opex", "legal", "capex"):
        client.post(f"/api/period/{P}/component", json={"component": c, "complete": True})
    assert get_period(client)["checklist"]["can_sign_off"] is True
    assert client.post(f"/api/period/{P}/signoff").status_code == 200
    r = client.post(f"/api/period/{P}/override", json={"key": "V1001|60200", "amount": "1", "explanation": "Late one"})
    assert r.status_code == 423
    h = client.get(f"/api/history/{P}").get_json()
    assert h["snapshot"]["summary"]["totals"]["total"] == 403591.51
    assert client.get("/api/meta").get_json()["signoffs"][0]["period"] == P
