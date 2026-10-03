"""Store validation, override log, sign-off gate, period lock and history."""
import pytest

from accrual_workbook.engine import model
from accrual_workbook.engine.backup import build_workbook
from accrual_workbook.engine.journal import upload_csv
from accrual_workbook.engine.vendor_opex import ValidationError
from accrual_workbook.store import LockedPeriodError, SignOffBlocked, Store
from helpers import D, budget, config, inputs, monthly_bills, roster

P = "2026-09"


@pytest.fixture
def store():
    return Store(":memory:")


# ---------- overrides ----------

@pytest.mark.parametrize("amount,explanation", [
    (None, "Vendor quote"), ("", "Vendor quote"), ("-1", "Vendor quote"), ("abc", "Vendor quote"),
    ("100", ""), ("100", "abcd"),
])
def test_override_validation_rejects(store, amount, explanation):
    with pytest.raises(ValidationError):
        store.set_override(P, "V1|60100", amount, explanation, "u")


def test_override_saved_with_who_when_and_logged(store):
    store.set_override(P, "V1|60100", "0", "Billed in full", "u1")
    o = store.overrides(P)["V1|60100"]
    assert (o["amount"], o["explanation"], o["user"], o["period"]) == (D(0), "Billed in full", "u1", P)
    assert o["at"]
    with pytest.raises(ValidationError):
        store.remove_override(P, "V1|60100", "", "u1")  # removal needs an explanation
    store.remove_override(P, "V1|60100", "Back to formula", "u1")
    assert store.overrides(P) == {}
    assert [e["action"] for e in store.override_log(P, "V1|60100")] == ["removed", "set"]


def test_override_log_keeps_50_entries(store):
    for i in range(60):
        store.set_override(P, "V1|60100", str(i), f"Change {i:03d}", "u")
    log = store.override_log(P, "V1|60100")
    assert len(log) == 50 and log[0]["amount"] == "59"


# ---------- manual adds ----------

GOOD = {"period": P, "vendor": "New Co", "vendor_id": "V9", "gl_account": "65100", "amount": "250", "dept": "D1",
        "location": "L1", "item": "I1", "explanation": "Offsite deposit"}


@pytest.mark.parametrize("change", [
    {"vendor_id": "V1"},               # on the roster -> use an override
    {"gl_account": "6510"},            # not 5 digits
    {"amount": "0"},                   # must be > 0
    {"period": "2026-08"},             # current period only
    {"explanation": "abc"},            # explanation 5+
    {"dept": ""},                      # dims required
])
def test_manual_add_validation(store, change):
    with pytest.raises(ValidationError):
        store.add_manual({**GOOD, **change}, "u", roster_vendor_ids={"V1"}, current_period=P)


def test_manual_add_saved(store):
    store.add_manual(GOOD, "u", roster_vendor_ids={"V1"}, current_period=P)
    assert [m["amount"] for m in store.manual_adds(P)] == [D(250)]


# ---------- sign-off gate ----------

def gate_inputs():
    """One flagged standing line (no dated bill), one missing-dims attention item, one large swing."""
    mom_gl = [{"vendor_id": "V2", "vendor": "Vendor V2", "gl_account": 60100, "prior_bills": D(0),
               "prior_accrual": D(20000), "prior_reversal": D(0), "current_bills": D(0),
               "current_reversal": D(20000), "other": D(0)}]
    rows = monthly_bills("V2", 60100, 100, range(1, 3))
    for r in rows:
        r["department_name"] = r["location_name"] = ""
    return inputs(rows, [roster("V1", 60100), roster("V2", 60100)],
                  [budget("V1", 60100, 12000), budget("V2", 60100, 12000)], mom_gl=mom_gl)


GATE_CFG = config(standing={"baseline_month": "2026-08",
                            "rules": [{"vendor_id": "V1", "gl_account": 60100, "type": "unbilled", "rate": 750}]})


def run_synced(store, inp):
    res = model.run(P, inp, GATE_CFG, store.state(P))
    store.sync_attention(P, res["attention_candidates"])
    res["checklist"] = model.signoff_checklist(res, store.state(P))
    return res


def ok_items(res):
    return {i["id"]: i["ok"] for i in res["checklist"]["items"]}


def test_signoff_gate_blocks_then_unblocks(store):
    inp = gate_inputs()
    res = run_synced(store, inp)
    assert ok_items(res) == {"attention": False, "swings": False, "components": False, "standing": False, "je": True}
    with pytest.raises(SignOffBlocked):
        store.sign_off(P, res, "u", upload_csv(res["je"]), b"")

    for item in store.attention(P):
        with pytest.raises(ValidationError):
            store.update_attention(P, item["id"], {"status": "Resolved"}, "u")  # needs a resolution
        store.update_attention(P, item["id"], {"status": "Resolved", "resolution": "Dims added"}, "u")
    for row in res["mom"]["rows"]:
        if row["large_swing"]:
            store.set_reviewed(P, row["key"], True, "u")
    for c in ("vendor_opex", "legal", "capex"):
        store.set_component(P, c, True, "u")
    res = run_synced(store, inp)
    assert ok_items(res) == {"attention": True, "swings": True, "components": True, "standing": False, "je": True}
    assert not res["checklist"]["can_sign_off"]

    store.confirm_standing(P, "V1|60100", "u")
    res = run_synced(store, inp)
    assert res["checklist"]["can_sign_off"]

    csv_text, xlsx = upload_csv(res["je"]), build_workbook(res)
    store.sign_off(P, res, "u", csv_text, xlsx)
    assert store.is_locked(P)

    # locked month rejects every edit
    with pytest.raises(LockedPeriodError):
        store.set_override(P, "V1|60100", "10", "Late change", "u")
    with pytest.raises(LockedPeriodError):
        store.add_manual(GOOD, "u", {"V1"}, P)
    with pytest.raises(LockedPeriodError):
        store.set_component(P, "legal", False, "u")
    with pytest.raises(LockedPeriodError):
        store.save_legal(P, "LA", {"amount": "1"}, "u")

    # history re-downloads exactly what was saved
    saved = store.signoff(P)
    assert saved["je_csv"] == csv_text and saved["backup"] == xlsx
    assert saved["snapshot"]["summary"]["totals"]["total"] == float(res["totals"]["total"])
    assert [s["period"] for s in store.signoffs()] == [P]
    assert model.run(P, inp, GATE_CFG, store.state(P))["checklist"]["can_sign_off"] is False  # already locked


def test_unreviewing_a_swing_reblocks(store):
    inp = gate_inputs()
    store.set_reviewed(P, "V2|60100", True, "u")
    assert ok_items(run_synced(store, inp))["swings"] is True
    store.set_reviewed(P, "V2|60100", False, "u")
    assert ok_items(run_synced(store, inp))["swings"] is False


def test_signoff_blocked_when_je_checks_fail(store):
    """Fifth blocker: a JE that does not tie can never be signed off."""
    inp = gate_inputs()
    cfg = config(standing=GATE_CFG["standing"],
                 je={"dept_splits": [{"vendor_id": "V2", "gl_account": 60100,
                                      "shares": [{"dept": "D1", "share": 0.5}, {"dept": "D2", "share": 0.4}]}]})
    res = model.run(P, inp, cfg, model.State(components={c: {"user": "u", "at": "t"} for c in ("vendor_opex", "legal", "capex")},
                                             standing_confirmed={"V1|60100"},
                                             mom_reviewed={"V2|60100": {"user": "u", "at": "t"}}))
    items = {i["id"]: i for i in res["checklist"]["items"]}
    assert items["je"]["ok"] is False and "Vendor OpEx = Tab 2" in items["je"]["detail"]
    assert all(i["ok"] for k, i in items.items() if k != "je")
    assert res["checklist"]["can_sign_off"] is False
