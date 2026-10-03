"""SQLite store: overrides, manual adds, legal edits, needs-attention, reviews, sign-off history.

Every write checks the period lock first; a signed-off month rejects edits.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .engine.legal import validate_legal_edit, validate_split
from .engine.model import State, jsonable
from .engine.money import D
from .engine.vendor_opex import ValidationError, validate_explanation, validate_manual_add, validate_override

OVERRIDE_LOG_LIMIT = 50
ATTENTION_STATUSES = ("Open", "In review", "Resolved")
COMPONENT_NAMES = ("vendor_opex", "legal", "capex")

SCHEMA = """
create table if not exists overrides (
  period text, key text, amount text not null, explanation text not null, user text, at text,
  primary key (period, key));
create table if not exists override_log (
  id integer primary key autoincrement, period text, key text, action text, amount text,
  explanation text, user text, at text);
create table if not exists manual_adds (
  id integer primary key autoincrement, period text, vendor text, vendor_id text, gl_account integer,
  amount text, dept text, location text, item text, explanation text, user text, at text);
create table if not exists legal_edits (
  period text, vendor_id text, data text, user text, at text, primary key (period, vendor_id));
create table if not exists legal_added (
  id integer primary key autoincrement, period text, data text, user text, at text);
create table if not exists standing_confirmations (
  period text, key text, user text, at text, primary key (period, key));
create table if not exists mom_reviews (
  period text, key text, user text, at text, primary key (period, key));
create table if not exists components (
  period text, component text, user text, at text, primary key (period, component));
create table if not exists attention (
  id integer primary key autoincrement, period text, key text, category text, vendor text, vendor_id text,
  account text, amount text, summary text, detail text, proposed text, assignee text,
  status text default 'Open', resolution text, source text, created_at text, updated_at text,
  unique (period, key));
create table if not exists signoffs (
  period text primary key, user text, at text, total text, snapshot text, je_csv text, backup blob);
"""


class LockedPeriodError(PermissionError):
    """The period is signed off and read-only."""


class SignOffBlocked(RuntimeError):
    """Sign-off checklist is not complete."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---------- lock ----------
    def is_locked(self, period: str) -> bool:
        return self.db.execute("select 1 from signoffs where period=?", (period,)).fetchone() is not None

    def _require_unlocked(self, period: str) -> None:
        if self.is_locked(period):
            raise LockedPeriodError(f"{period} is signed off and locked; edits are not allowed.")

    # ---------- overrides ----------
    def set_override(self, period, key, amount, explanation, user):
        self._require_unlocked(period)
        validate_override(amount, explanation)
        amt, at = str(D(amount)), _now()
        self.db.execute("insert or replace into overrides values (?,?,?,?,?,?)",
                        (period, key, amt, explanation.strip(), user, at))
        self._log(period, key, "set", amt, explanation.strip(), user, at)
        self.db.commit()

    def remove_override(self, period, key, explanation, user):
        self._require_unlocked(period)
        validate_explanation(explanation)
        if not self.db.execute("select 1 from overrides where period=? and key=?", (period, key)).fetchone():
            raise ValidationError("No override to remove.")
        self.db.execute("delete from overrides where period=? and key=?", (period, key))
        self._log(period, key, "removed", None, explanation.strip(), user, _now())
        self.db.commit()

    def _log(self, period, key, action, amount, explanation, user, at):
        self.db.execute("insert into override_log (period,key,action,amount,explanation,user,at) values (?,?,?,?,?,?,?)",
                        (period, key, action, amount, explanation, user, at))
        self.db.execute("""delete from override_log where period=? and key=? and id not in (
                             select id from override_log where period=? and key=? order by id desc limit ?)""",
                        (period, key, period, key, OVERRIDE_LOG_LIMIT))

    def override_log(self, period, key) -> list[dict]:
        rows = self.db.execute("select * from override_log where period=? and key=? order by id desc", (period, key))
        return [dict(r) for r in rows]

    def overrides(self, period) -> dict:
        rows = self.db.execute("select * from overrides where period=?", (period,))
        return {r["key"]: {"amount": D(r["amount"]), "explanation": r["explanation"], "user": r["user"], "at": r["at"],
                           "period": period} for r in rows}

    # ---------- manual adds ----------
    def add_manual(self, entry: dict, user: str, roster_vendor_ids, current_period: str) -> int:
        period = str(entry.get("period"))
        self._require_unlocked(period)
        validate_manual_add(entry, roster_vendor_ids, current_period)
        cur = self.db.execute(
            "insert into manual_adds (period,vendor,vendor_id,gl_account,amount,dept,location,item,explanation,user,at)"
            " values (?,?,?,?,?,?,?,?,?,?,?)",
            (period, entry["vendor"].strip(), str(entry["vendor_id"]).strip(), int(entry["gl_account"]),
             str(D(entry["amount"])), entry["dept"], entry["location"], entry["item"], entry["explanation"].strip(),
             user, _now()))
        self.db.commit()
        return cur.lastrowid

    def delete_manual(self, period, manual_id):
        self._require_unlocked(period)
        self.db.execute("delete from manual_adds where period=? and id=?", (period, manual_id))
        self.db.commit()

    def manual_adds(self, period) -> list[dict]:
        rows = self.db.execute("select * from manual_adds where period=? order by id", (period,))
        return [{**dict(r), "amount": D(r["amount"])} for r in rows]

    # ---------- legal ----------
    def save_legal(self, period, vendor_id, fields: dict, user, splits: list | None = None):
        self._require_unlocked(period)
        validate_legal_edit(fields)
        data = {k: (str(v) if k == "amount" else v) for k, v in fields.items()}
        if splits:
            validate_split(splits)
            data["splits"] = [{**s, "amount": str(D(s["amount"]))} for s in splits]
        else:
            data["splits"] = None
        self.db.execute("insert or replace into legal_edits values (?,?,?,?,?)",
                        (period, vendor_id, json.dumps(data), user, _now()))
        self.db.commit()

    def add_legal_vendor(self, period, row: dict, user) -> int:
        self._require_unlocked(period)
        for f in ("vendor", "vendor_id"):
            if not str(row.get(f) or "").strip():
                raise ValidationError(f"Legal vendor needs {f.replace('_', ' ')}.")
        validate_legal_edit({k: row[k] for k in ("amount", "gl") if k in row})
        cur = self.db.execute("insert into legal_added (period,data,user,at) values (?,?,?,?)",
                              (period, json.dumps({k: str(v) for k, v in row.items()}), user, _now()))
        self.db.commit()
        return cur.lastrowid

    def legal_edits(self, period) -> dict:
        return {r["vendor_id"]: json.loads(r["data"])
                for r in self.db.execute("select * from legal_edits where period=?", (period,))}

    def legal_added(self, period) -> list[dict]:
        return [json.loads(r["data"]) for r in self.db.execute("select * from legal_added where period=? order by id",
                                                                (period,))]

    # ---------- confirmations / reviews / components ----------
    def confirm_standing(self, period, key, user):
        self._require_unlocked(period)
        self.db.execute("insert or replace into standing_confirmations values (?,?,?,?)", (period, key, user, _now()))
        self.db.commit()

    def set_reviewed(self, period, key, reviewed: bool, user):
        self._require_unlocked(period)
        if reviewed:
            self.db.execute("insert or replace into mom_reviews values (?,?,?,?)", (period, key, user, _now()))
        else:
            self.db.execute("delete from mom_reviews where period=? and key=?", (period, key))
        self.db.commit()

    def set_component(self, period, component, complete: bool, user):
        self._require_unlocked(period)
        if component not in COMPONENT_NAMES:
            raise ValidationError(f"Unknown component {component!r}.")
        if complete:
            self.db.execute("insert or replace into components values (?,?,?,?)", (period, component, user, _now()))
        else:
            self.db.execute("delete from components where period=? and component=?", (period, component))
        self.db.commit()

    # ---------- needs attention ----------
    def sync_attention(self, period, candidates: list[dict]):
        """Insert new system items; keep the status/resolution of ones already seen."""
        if self.is_locked(period):
            return
        for c in candidates:
            self.db.execute(
                "insert or ignore into attention (period,key,category,vendor,vendor_id,account,amount,summary,detail,"
                "proposed,assignee,status,resolution,source,created_at,updated_at)"
                " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (period, c["key"], c["category"], c.get("vendor", ""), c.get("vendor_id", ""),
                 str(c.get("account") or ""), str(c.get("amount") or 0), c["summary"], c.get("detail", ""),
                 c.get("proposed", ""), "", "Open", "", "system", _now(), _now()))
        self.db.commit()

    def add_attention(self, period, item: dict, user) -> int:
        self._require_unlocked(period)
        if not str(item.get("summary") or "").strip():
            raise ValidationError("Summary is required.")
        key = f"manual|{datetime.now().timestamp()}"
        cur = self.db.execute(
            "insert into attention (period,key,category,vendor,vendor_id,account,amount,summary,detail,proposed,"
            "assignee,status,resolution,source,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (period, key, item.get("category", "Other"), item.get("vendor", ""), item.get("vendor_id", ""),
             str(item.get("account") or ""), str(D(item.get("amount") or 0)), item["summary"], item.get("detail", ""),
             item.get("proposed", ""), item.get("assignee", ""), "Open", "", f"manual:{user}", _now(), _now()))
        self.db.commit()
        return cur.lastrowid

    def update_attention(self, period, item_id, fields: dict, user):
        self._require_unlocked(period)
        if "status" in fields and fields["status"] not in ATTENTION_STATUSES:
            raise ValidationError(f"Status must be one of {', '.join(ATTENTION_STATUSES)}.")
        if fields.get("status") == "Resolved" and not str(fields.get("resolution") or self._attention_field(
                item_id, "resolution") or "").strip():
            raise ValidationError("A resolution note is required to resolve an item.")
        allowed = {k: v for k, v in fields.items() if k in ("assignee", "status", "resolution")}
        for k, v in allowed.items():
            self.db.execute(f"update attention set {k}=?, updated_at=? where id=? and period=?",
                            (v, _now(), item_id, period))
        self.db.commit()

    def _attention_field(self, item_id, field):
        r = self.db.execute(f"select {field} from attention where id=?", (item_id,)).fetchone()
        return r[0] if r else None

    def attention(self, period=None) -> list[dict]:
        if period:
            rows = self.db.execute("select * from attention where period=? order by id", (period,))
        else:
            rows = self.db.execute("select * from attention order by period, id")
        return [{**dict(r), "amount": D(r["amount"])} for r in rows]

    # ---------- state for the engine ----------
    def state(self, period) -> State:
        q = self.db.execute
        return State(
            overrides=self.overrides(period),
            manual_adds=self.manual_adds(period),
            legal_edits=self.legal_edits(period),
            legal_added=self.legal_added(period),
            standing_confirmed={r["key"] for r in q("select key from standing_confirmations where period=?", (period,))},
            mom_reviewed={r["key"]: {"user": r["user"], "at": r["at"]}
                          for r in q("select * from mom_reviews where period=?", (period,))},
            components={r["component"]: {"user": r["user"], "at": r["at"]}
                        for r in q("select * from components where period=?", (period,))},
            attention=self.attention(period),
            locked=self.is_locked(period),
            signoff=self.signoff(period, with_files=False),
        )

    # ---------- sign-off ----------
    def sign_off(self, period, result: dict, user, je_csv: str, backup: bytes):
        self._require_unlocked(period)
        if not result["checklist"]["can_sign_off"]:
            failing = [i["label"] for i in result["checklist"]["items"] if not i["ok"]]
            raise SignOffBlocked("Sign-off blocked: " + "; ".join(failing))
        snapshot = jsonable({
            "summary": {"totals": result["totals"], "components": result["components"],
                        "period_label": result["period_label"], "company": result["company"]},
            "vendor_opex": result["vendor_opex"]["lines"], "legal": result["legal"],
            "capex": {k: result["capex"][k] for k in ("groups", "deals", "total", "not_final", "unallocated_gl")},
            "je": result["je"],
            # what next month's MoM review needs: this month's accruals and the ones they replaced
            "mom_basis": {"accruals": {r["key"]: r["current_accrual"] for r in result["mom"]["rows"]
                                       if r["current_accrual"]},
                          "prior_accruals": {r["key"]: r["prior_accrual"] for r in result["mom"]["rows"]
                                             if r["prior_accrual"]}},
        })
        self.db.execute("insert into signoffs values (?,?,?,?,?,?,?)",
                        (period, user, _now(), str(result["totals"]["total"]), json.dumps(snapshot), je_csv, backup))
        self.db.commit()

    def signoff(self, period, with_files: bool = True) -> dict | None:
        r = self.db.execute("select * from signoffs where period=?", (period,)).fetchone()
        if not r:
            return None
        out = {"period": r["period"], "user": r["user"], "at": r["at"], "total": D(r["total"])}
        if with_files:
            out.update({"snapshot": json.loads(r["snapshot"]), "je_csv": r["je_csv"], "backup": bytes(r["backup"])})
        return out

    def signoffs(self) -> list[dict]:
        return [{"period": r["period"], "user": r["user"], "at": r["at"], "total": D(r["total"])}
                for r in self.db.execute("select period,user,at,total from signoffs order by period desc")]
