"""Glue between the engine and the store: run a period with saved edits, sync needs-attention,
and switch between the sample data set and the user's own data."""
from __future__ import annotations

import copy
import os
from pathlib import Path

from . import datasets
from .engine import model, mom
from .engine.config import load_config
from .engine.loader import Inputs, load_inputs
from .engine.money import D
from .engine.period import Period
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data" / "sample"
DEFAULT_CONFIG = ROOT / "config" / "rules.yaml"
DEFAULT_DB = ROOT / "data" / "workbook.db"
DEFAULT_USER_DIR = ROOT / "data" / "user"

SAMPLE, USER = "sample", "user"
DATASET_LABELS = {SAMPLE: "Sample data", USER: "My data"}


class Workbook:
    def __init__(self, data_dir=None, config_path=None, db_path=None, user_dir=None, dataset: str = SAMPLE):
        self.sample_paths = (
            Path(data_dir or os.environ.get("ACCRUAL_DATA", DEFAULT_DATA)),
            Path(config_path or os.environ.get("ACCRUAL_CONFIG", DEFAULT_CONFIG)),
            Path(db_path or os.environ.get("ACCRUAL_DB", DEFAULT_DB)),
        )
        self.user_dir = Path(user_dir or os.environ.get("ACCRUAL_USER_DIR", DEFAULT_USER_DIR))
        self.store = None
        self.activate(dataset)

    # ---------- data sets ----------
    @property
    def choice_file(self) -> Path:
        return self.user_dir.parent / "active_dataset.txt"

    @classmethod
    def remembered(cls, data_dir=None, config_path=None, db_path=None, user_dir=None) -> "Workbook":
        """Open the data set chosen last time on the Settings tab (falls back to sample data)."""
        wb = cls(data_dir, config_path, db_path, user_dir)
        try:
            if wb.choice_file.read_text(encoding="utf-8").strip() == USER:
                wb.activate(USER)
        except OSError:
            pass
        except Exception:  # noqa: BLE001 - a broken user data set must not stop the app
            wb.activate(SAMPLE)
        return wb

    def paths(self, dataset: str):
        if dataset == USER:
            return self.user_dir, self.user_dir / "rules.yaml", self.user_dir / "workbook.db"
        return self.sample_paths

    def activate(self, dataset: str, remember: bool = False) -> None:
        if dataset not in DATASET_LABELS:
            raise ValueError(f"Unknown data set {dataset!r}.")
        if dataset == USER:
            datasets.ensure_user_folder(self.user_dir, self.sample_paths[1])
        data_dir, config_path, db_path = self.paths(dataset)
        cfg, inputs = load_config(config_path), load_inputs(data_dir)
        if self.store is not None:
            self.store.db.close()
        self.dataset, self.data_dir, self.config_path = dataset, data_dir, config_path
        self.cfg, self.inputs = cfg, inputs
        self.store = Store(db_path)
        if remember:
            self.choice_file.parent.mkdir(parents=True, exist_ok=True)
            self.choice_file.write_text(dataset, encoding="utf-8")

    def reload(self) -> None:
        self.cfg = load_config(self.config_path)
        self.inputs = load_inputs(self.data_dir)

    # ---------- running ----------
    @property
    def user(self) -> str:
        return self.cfg["user"]

    @property
    def roster_vendor_ids(self) -> set:
        return {r["vendor_id"] for r in self.inputs.roster}

    def inputs_for(self, period: str) -> tuple[Inputs, str]:
        """Last month's JE, its dimensions and the MoM figures come from this app's own sign-off of the
        previous month when there is one; otherwise from the uploaded files."""
        prev = Period.parse(period).prev()
        saved = self.store.signoff(prev.key)
        if not saved:
            return self.inputs, "uploaded files"
        snap = saved["snapshot"]
        debits = [ln for ln in snap["je"]["lines"] if ln["side"] == "debit"]
        inp = copy.copy(self.inputs)
        inp.prior_je = [{"je_id": snap["je"]["header"]["reference"], "acct": int(ln["acct"]),
                         "vendor_id": ln["vendor_id"], "vendor": ln["vendor_name"], "dept": ln["dept"],
                         "amount": D(ln["debit"])} for ln in debits]
        inp.prior_je_meta = {"period": prev.key, "reversed_total": sum((p["amount"] for p in inp.prior_je), D(0))}
        hist_dims, seen = [], set()
        for ln in debits:
            k = (ln["vendor_id"], int(ln["acct"]))
            if ln["section"] == "Vendor OpEx" and k not in seen and ln["dept"]:
                seen.add(k)
                hist_dims.append({"vendor_id": k[0], "gl_account": k[1], "dept": ln["dept"],
                                  "location": ln["location"], "item": ln["item"], "source": "prior_je"})
        inp.je_dims = hist_dims + list(self.inputs.je_dims)
        basis = snap.get("mom_basis") or {}
        names = {r["vendor_id"]: r["vendor_name"] for r in self.inputs.roster}
        inp.mom_gl = mom.derive_mom_gl(self.inputs.gl, self.cfg, Period.parse(period), basis.get("accruals", {}),
                                       basis.get("prior_accruals", {}), names)
        return inp, f"{prev.label} sign-off in this app"

    def run(self, period: str) -> dict:
        inputs, source = self.inputs_for(period)
        result = model.run(period, inputs, self.cfg, self.store.state(period))
        result["prior_source"] = source
        if not result["locked"]:
            self.store.sync_attention(period, result["attention_candidates"])
            # re-run the checklist with the synced attention items
            result["checklist"] = model.signoff_checklist(result, self.store.state(period))
        return result

    def current_period(self) -> str:
        if self.cfg.get("current_period"):
            return Period.parse(str(self.cfg["current_period"])).key
        if self.inputs.gl:
            return Period.parse(max(r["posting_date"] for r in self.inputs.gl).strftime("%Y-%m")).key
        return datasets.default_period()

    def rollover(self, period: str) -> dict:
        """Close a signed-off month and open the next one (My data only).

        Standing rules keep applying (the first closed month becomes their baseline if none is set) and
        this month's manual adds are carried forward as fixed carried manual adds, flagged when a new bill
        arrives. Overrides are current-month only and do not carry.
        """
        if self.dataset != USER:
            raise datasets.DatasetError("The sample data is a fixed demo. Start next month works on My data.")
        if period != self.current_period():
            raise datasets.DatasetError(f"Only the open month ({self.current_period()}) can be rolled forward.")
        if not self.store.is_locked(period):
            raise datasets.DatasetError(f"Sign off {period} before starting the next month.")
        p = Period.parse(period)
        rules = datasets.read_rules(self.data_dir)
        rules["current_period"] = p.next().key
        st = rules.setdefault("standing", {}) or {}
        rules["standing"] = st
        if not st.get("baseline_month"):
            st["baseline_month"] = p.key
        carried = {f"{c['vendor_id']}|{int(c['gl_account'])}": c for c in st.get("carried_manual_adds") or []}
        for m in self.store.manual_adds(period):
            carried[f"{m['vendor_id']}|{int(m['gl_account'])}"] = {
                "vendor": m["vendor"], "vendor_id": m["vendor_id"], "gl_account": int(m["gl_account"]),
                "type": "fixed", "amount": str(m["amount"]), "dept": m["dept"], "location": m["location"],
                "item": m["item"], "owner": m["user"],
                "explanation": f"Carried from {p.label}: {m['explanation']}",
            }
        st["carried_manual_adds"] = list(carried.values())
        datasets.write_rules(self.data_dir / "rules.yaml", rules)
        self.reload()
        return {"next": p.next().key, "carried_manual_adds": len(st["carried_manual_adds"]),
                "baseline_month": st["baseline_month"]}
