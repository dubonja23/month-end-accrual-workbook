"""Settings tab: switching to your own data and uploading CSVs with validation."""
import io

import pytest

from accrual_workbook.api import create_app
from accrual_workbook.runner import DEFAULT_CONFIG


@pytest.fixture
def client(sample_dir, tmp_path):
    app = create_app(sample_dir, DEFAULT_CONFIG, tmp_path / "sample.db", tmp_path / "user")
    c = app.test_client()
    c.tmp = tmp_path
    return c


def upload(client, name, text):
    return client.post(f"/api/settings/upload/{name}", data={"file": (io.BytesIO(text.encode("utf-8")), name)},
                       content_type="multipart/form-data")


def to_user(client):
    assert client.post("/api/settings/dataset", json={"dataset": "user"}).status_code == 200


def test_sample_data_is_read_only(client):
    r = upload(client, "roster.csv", "vendor_id\nV1\n")
    assert r.status_code == 400 and "read-only" in r.get_json()["error"]


def test_new_user_dataset_starts_empty_and_runs(client):
    to_user(client)
    meta = client.get("/api/meta").get_json()
    assert meta["dataset"] == "user" and meta["company"] == "My Company"
    d = client.get(f"/api/period/{meta['current_period']}").get_json()
    assert d["totals"]["total"] == 0 and d["je"]["lines"] == []
    s = client.get("/api/settings").get_json()
    assert [f["rows"] for f in s["files"]] == [0] * 9
    assert (client.tmp / "user" / "rules.yaml").exists()


def test_upload_rejects_missing_columns_and_names_them(client):
    to_user(client)
    r = upload(client, "roster.csv", "vendor_id,gl_account\nV1,60100\n")
    err = r.get_json()["error"]
    assert r.status_code == 400 and "missing columns" in err and "owner" in err


def test_upload_rejects_bad_rows_with_row_numbers(client):
    to_user(client)
    text = "dim_type,id,name\naccount,60100,Professional Services\n,,No type\n"
    r = upload(client, "dimension_names.csv", text)
    assert r.status_code == 400 and "row 3" in r.get_json()["error"]
    text = ("vendor_id,vendor_name,gl_account,gl_account_name,jan,feb,mar,apr,may,jun,jul,aug,sep,oct,nov,dec,annual\n"
            "V1,Test Vendor,60100,Prof,100,100,abc,100,100,100,100,100,100,100,100,100,1200\n")
    r = upload(client, "budget.csv", text)
    assert r.status_code == 400 and "row 2" in r.get_json()["error"] and "abc" in r.get_json()["error"]


def test_upload_valid_files_flow_into_the_accrual(client):
    to_user(client)
    assert upload(client, "dimension_names.csv",
                  "dim_type,id,name\naccount,60100,Professional Services\ndept,D1,Finance\nlocation,L1,Main\n"
                  ).get_json()["rows"] == 3
    budget = ("Vendor ID,Vendor Name,GL Account,GL Account Name,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec,Annual\n"
              "V1,Test Vendor,60100,Professional Services,1000,1000,1000,1000,1000,1000,1000,1000,1000,1000,1000,1000,12000\n")
    assert upload(client, "budget.csv", budget).status_code == 200  # Excel-style headers are accepted
    roster = ("vendor_name,vendor_id,gl_account,gl_account_name,vendor_type,budget_ytd_spread,gl_actual_ytd,"
              "liability_prior_year_remaining,owner\nTest Vendor,V1,60100,Professional Services,Services,0,0,0,Pat\n")
    assert upload(client, "roster.csv", roster).status_code == 200
    assert client.post("/api/settings/general", json={"company": "Test Co", "current_period": "2026-09"}).status_code == 200
    d = client.get("/api/period/2026-09").get_json()
    assert d["company"] == "Test Co"
    assert d["totals"]["vendor_opex"] == 9000.0  # 12,000 x 9/12, nothing billed
    s = client.get("/api/settings").get_json()
    assert {f["name"]: f["rows"] for f in s["files"]}["roster.csv"] == 1


def test_inputs_meta_and_reset(client):
    to_user(client)
    r = client.post("/api/settings/inputs-meta", json={"unallocated_gl_total": "1500", "needs_attention_count": "2",
                                                       "needs_attention_total": "1500", "prior_period": "2026-08",
                                                       "reversed_total": "0"})
    assert r.status_code == 200
    assert client.get("/api/settings").get_json()["inputs_meta"]["unallocated_gl_total"] == 1500.0
    assert client.post("/api/settings/reset", json={"confirm": "no"}).status_code == 400
    assert client.post("/api/settings/reset", json={"confirm": "RESET"}).status_code == 200
    assert client.get("/api/settings").get_json()["inputs_meta"]["unallocated_gl_total"] == 0.0


def test_switching_back_to_sample_keeps_sample_totals(client):
    to_user(client)
    client.post("/api/settings/dataset", json={"dataset": "sample"})
    assert client.get("/api/period/2026-09").get_json()["totals"]["total"] == 403591.51


def test_templates_download(client):
    r = client.get("/api/settings/template/roster.csv")
    assert r.status_code == 200 and r.data.decode().startswith("vendor_name,vendor_id,gl_account")
    assert client.get("/api/settings/example/roster.csv").status_code == 200
