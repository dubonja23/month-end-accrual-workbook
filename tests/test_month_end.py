"""Month-end flow on My data: sign off, start next month, history-fed prior-month inputs, cross-file checks."""
import shutil

import pytest

from accrual_workbook import datasets
from accrual_workbook.engine.backup import build_workbook
from accrual_workbook.engine.journal import upload_csv
from accrual_workbook.runner import DEFAULT_CONFIG, SAMPLE, USER, Workbook
from helpers import D, budget, config, inputs, roster


@pytest.fixture
def wb(sample_dir, tmp_path):
    """A My data set that starts as a copy of the sample files and rules."""
    user = tmp_path / "user"
    shutil.copytree(sample_dir, user)
    shutil.copy(DEFAULT_CONFIG, user / "rules.yaml")
    w = Workbook(sample_dir, DEFAULT_CONFIG, tmp_path / "sample.db", user, dataset=SAMPLE)
    w.activate(USER)
    return w


def sign_off(w, period):
    res = w.run(period)
    for item in w.store.attention(period):
        w.store.update_attention(period, item["id"], {"status": "Resolved", "resolution": "Checked"}, "u")
    for row in res["mom"]["rows"]:
        if row["large_swing"]:
            w.store.set_reviewed(period, row["key"], True, "u")
    for t in res["standing"]["table"]:
        if t["needs_confirm"]:
            w.store.confirm_standing(period, t["key"], "u")
    for c in ("vendor_opex", "legal", "capex"):
        w.store.set_component(period, c, True, "u")
    res = w.run(period)
    assert res["checklist"]["can_sign_off"], res["checklist"]
    w.store.sign_off(period, res, "u", upload_csv(res["je"]), build_workbook(res))
    return res


MANUAL = {"period": "2026-09", "vendor": "Lumen Kite Studio", "vendor_id": "V5001", "gl_account": "64200",
          "amount": "1500", "dept": "D400", "location": "L10", "item": "I-MKT", "explanation": "Offsite deposit"}


def test_rollover_requires_sign_off_and_open_month(wb):
    with pytest.raises(datasets.DatasetError, match="Sign off"):
        wb.rollover("2026-09")
    with pytest.raises(datasets.DatasetError, match="open month"):
        wb.rollover("2026-08")


def test_rollover_not_allowed_on_sample_data(sample_dir, tmp_path):
    w = Workbook(sample_dir, DEFAULT_CONFIG, tmp_path / "s.db", tmp_path / "user")
    with pytest.raises(datasets.DatasetError, match="fixed demo"):
        w.rollover("2026-09")


def test_month_end_rollover_and_history_fed_inputs(wb):
    assert wb.run("2026-09")["prior_source"] == "uploaded files"
    wb.store.add_manual(MANUAL, "u", wb.roster_vendor_ids, "2026-09")
    sep = sign_off(wb, "2026-09")

    out = wb.rollover("2026-09")
    assert out["next"] == "2026-10" and wb.current_period() == "2026-10"
    rules = datasets.read_rules(wb.data_dir)
    carried = {c["vendor_id"]: c for c in rules["standing"]["carried_manual_adds"]}
    assert "V5001" in carried and "V1040" in carried  # this month's manual add + the existing carried one
    assert carried["V5001"]["explanation"].startswith("Carried from Sep 2026")

    oct_ = wb.run("2026-10")
    assert oct_["prior_source"] == "Sep 2026 sign-off in this app"
    # last month's JE = the September JE saved at sign-off
    assert oct_["prior_je"]["reversed_total"] == sep["je"]["total_debits"]
    rows = {r["key"]: r for r in oct_["mom"]["rows"]}
    sep_rows = {r["key"]: r for r in sep["mom"]["rows"]}
    k = "V1005|61200"  # Tallreed: 12,500 accrued in September
    assert rows[k]["prior_accrual"] == D("12500.00") == rows[k]["current_reversal"]
    assert rows[k]["prior_reversal"] == sep_rows[k]["prior_accrual"]  # August accrual, reversed Sep 1
    # September's manual add is now a carried manual add in October
    v5001 = next(ln for ln in oct_["vendor_opex"]["lines"] if ln["key"] == "V5001|64200")
    assert (v5001["line_type"], v5001["final_accrual"]) == ("carried", D("1500.00"))
    # dimensions come from last month's JE
    v1001 = next(ln for ln in oct_["vendor_opex"]["lines"] if ln["key"] == "V1005|61200")
    assert v1001["dims"]["source"] == "prior_je"


# ---------- cross-file checks ----------

def test_cross_checks_flag_mismatches_between_files():
    inp = inputs(roster_rows=[roster("V1", 60100), roster("V1", 60100), roster("V2", 70100), roster("V3", 60300)],
                 budget_rows=[budget("V1", 60100, 1200), budget("V9", 60200, 500)])
    inp.dim_names = {"account": {"60100": "Prof"}, "dept": {"D1": "Finance"}}
    checks = {c["message"]: c for c in datasets.cross_checks(inp, config(), "2026-09")}
    roster_not_in_coa = checks["Roster accounts that are not in the chart of accounts"]
    assert roster_not_in_coa["level"] == "error" and roster_not_in_coa["examples"] == ["60300", "70100"]
    assert checks["Budget accounts that are not in the chart of accounts"]["examples"] == ["60200"]
    assert checks["Duplicate roster lines (same vendor + account); spend would be counted twice"]["examples"] == \
        ["V1 | 60100"]
    assert checks["Roster lines on accounts outside the accrual scope; they can never receive spend"]["examples"] \
        == ["V2 | 70100"]
    no_budget = [c for m, c in checks.items() if m.startswith("Roster lines with no budget")][0]
    assert no_budget["examples"] == ["V2 | 70100", "V3 | 60300"]


def test_cross_checks_missing_chart_of_accounts():
    inp = inputs(roster_rows=[roster("V1", 60100)])
    inp.dim_names = {}
    assert datasets.cross_checks(inp, config(), "2026-09")[0]["message"].startswith("No chart of accounts")


def test_sample_data_has_no_cross_file_errors(sample_dir, tmp_path):
    w = Workbook(sample_dir, DEFAULT_CONFIG, tmp_path / "s.db", tmp_path / "user")
    levels = [c["level"] for c in datasets.cross_checks(w.inputs, w.cfg, "2026-09")]
    assert "error" not in levels and "warning" not in levels
