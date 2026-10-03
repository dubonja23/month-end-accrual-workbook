"""Service-month assignment, prepaid day split, rollups, service rules and spend buckets."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import key_of
from .money import ZERO, D, r2
from .period import MONTH_ABBR, Period, month_end, month_key

CONFIRMED = "Confirmed"
ESTIMATED = "Estimated"

SRC_FIELD = "Service period"
SRC_MEMO = "Memo"
SRC_POSTING = "Posting month"

_MONTHS = {m.lower(): i + 1 for i, m in enumerate(MONTH_ABBR)}
_RE_FULL_DATE = re.compile(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(20\d{2})\b")
_RE_ISO_MONTH = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])(?:-\d{2})?\b")
_RE_SLASH_MONTH = re.compile(r"\b(0?[1-9]|1[0-2])/(20\d{2})\b")
_RE_NAME_MONTH = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[\s\-']*(20\d{2}|\d{2})\b", re.I
)


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def parse_memo_month(text: str) -> str | None:
    """Find a service month in a bill memo. Returns 'YYYY-MM' or None.

    Accepted: 09/15/2026, 2026-09 (or 2026-09-15), 09/2026, 'Sep 2026', 'September 2026', "Sep '26", 'Sep-26'.
    """
    if not text:
        return None
    m = _RE_FULL_DATE.search(text)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}"
    m = _RE_ISO_MONTH.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = _RE_SLASH_MONTH.search(text)
    if m:
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"
    m = _RE_NAME_MONTH.search(text)
    if m:
        year = int(m.group(2))
        year = year + 2000 if year < 100 else year
        return f"{year:04d}-{_MONTHS[m.group(1).lower()[:3]]:02d}"
    return None


def matching_service_rule(row: dict, cfg: dict) -> dict | None:
    for rule in cfg.get("service_rules", []) or []:
        if str(rule["vendor_id"]) != row["vendor_id"]:
            continue
        accounts = rule.get("accounts")
        if accounts and row["gl_account"] not in {int(a) for a in accounts}:
            continue
        lo, hi = _as_date(rule.get("posting_from")), _as_date(rule.get("posting_to"))
        if lo and row["posting_date"] < lo:
            continue
        if hi and row["posting_date"] > hi:
            continue
        return rule
    return None


def assign_service_month(row: dict, cfg: dict) -> tuple[str, str, str]:
    """Return (service_month 'YYYY-MM', source label, basis Confirmed/Estimated).

    Priority: a configured service rule forces the month; then (1) the bill's service-period field;
    (2) a date or month parsed from the memo; (3) the posting month (Estimated).
    """
    rule = matching_service_rule(row, cfg)
    if rule:
        return str(rule["service_month"]), str(rule.get("source", "Service rule")), rule.get("basis", CONFIRMED)
    if row.get("service_from"):
        return month_key(row["service_from"]), SRC_FIELD, CONFIRMED
    if row.get("service_month_field"):
        return row["service_month_field"][:7], SRC_FIELD, CONFIRMED
    memo = parse_memo_month(row.get("description", ""))
    if memo:
        return memo, SRC_MEMO, CONFIRMED
    return month_key(row["posting_date"]), SRC_POSTING, ESTIMATED


# ---------- rollups ----------

def map_vendor(vendor_id: str, acct: int, cfg: dict) -> str:
    for r in cfg["rollups"].get("vendor", []) or []:
        if str(r["from_vendor_id"]) == vendor_id and int(r["gl_account"]) == acct:
            return str(r["to_vendor_id"])
    return vendor_id


def map_account(vendor_id: str, acct: int, cfg: dict, original_vendor: str | None = None) -> int:
    for r in cfg["rollups"].get("account", []) or []:
        rv = str(r.get("vendor_id") or "")
        if rv and rv not in {vendor_id, original_vendor}:
            continue
        if int(r["from_account"]) == acct:
            return int(r["to_account"])
    return acct


def map_key(vendor_id: str, acct: int, cfg: dict) -> tuple[str, int]:
    """Vendor rollup first (X|acct -> Y|acct), then account rollup (vendor|A -> vendor|B)."""
    v = map_vendor(vendor_id, acct, cfg)
    a = map_account(v, acct, cfg, original_vendor=vendor_id)
    return key_of(v, a)


# ---------- prepaid ----------

def prepaid_split(amount, start: date, end: date, fy_start: date, fy_end: date) -> tuple:
    """Split a prepaid bill by days at both ends of the fiscal year.

    Returns (prior_year_share, current_year_share, next_year_share). The prior- and next-year shares are
    rounded to cents; the current-year share takes the remainder so the three always add up to the bill.
    """
    amount = D(amount)
    total_days = (end - start).days + 1
    if total_days <= 0:
        return ZERO, amount, ZERO
    prior_days = max(0, (min(end, fy_start - timedelta(days=1)) - start).days + 1)
    next_days = max(0, (end - max(start, fy_end + timedelta(days=1))).days + 1)
    prior = r2(amount * prior_days / total_days) if prior_days else ZERO
    nxt = r2(amount * next_days / total_days) if next_days else ZERO
    current = amount - prior - nxt
    if prior_days + next_days == total_days:  # no current-year days: keep the cents in the outer share
        if next_days:
            nxt += current
        else:
            prior += current
        current = ZERO
    return prior, current, nxt


# ---------- spend ----------

def new_spend() -> dict:
    return {
        "buckets": {},            # service month -> amount (current FY, Jan..cutoff month)
        "prior_year": ZERO,        # service before FY start (excluded from spend)
        "after_cutoff": ZERO,      # service after cutoff month (included)
        "prepaid_current": ZERO,   # prepaid current-year share (included)
        "prepaid_next": ZERO,      # prepaid next-year share (excluded)
        "gl_total": ZERO,          # every in-scope row mapped to the line
        "posted_this_period": ZERO,
        "row_ids": [],
    }


def spend_ytd(s: dict) -> object:
    return sum(s["buckets"].values(), ZERO) + s["prepaid_current"] + s["after_cutoff"]


@dataclass
class SpendContext:
    by_key: dict = field(default_factory=dict)
    prepaid_ignored: list = field(default_factory=list)  # prepaid rows not attributed (vendor has != 1 line)
    row_key: dict = field(default_factory=dict)          # row_id -> mapped key (for GL detail)

    def get(self, key) -> dict:
        return self.by_key.get(key) or new_spend()


def build_spend(rows: list[dict], roster_keys, cfg: dict, period: Period) -> SpendContext:
    ctx = SpendContext()
    lines_by_vendor: dict[str, list] = {}
    for k in roster_keys:
        lines_by_vendor.setdefault(k[0], []).append(k)
    fy_first = period.fy_month_keys()[0]
    for row in rows:
        if row["kind"] == "prepaid":
            vendor = map_vendor(row["vendor_id"], row["gl_account"], cfg)
            lines = lines_by_vendor.get(vendor, [])
            if len(lines) != 1:
                ctx.prepaid_ignored.append({**row, "roster_lines": len(lines)})
                continue
            key = lines[0]
            s = ctx.by_key.setdefault(key, new_spend())
            start = row["service_from"] or date(*map(int, row["service_month"].split("-")), 1)
            end = row["service_to"] or month_end(start.year, start.month)
            prior, cur, nxt = prepaid_split(row["amount"], start, end, period.fy_start, period.fy_end)
            s["prior_year"] += prior
            s["prepaid_current"] += cur
            s["prepaid_next"] += nxt
        else:
            key = map_key(row["vendor_id"], row["gl_account"], cfg)
            s = ctx.by_key.setdefault(key, new_spend())
            m = row["service_month"]
            if m < fy_first:
                s["prior_year"] += row["amount"]
            elif m > period.key:
                s["after_cutoff"] += row["amount"]
            else:
                s["buckets"][m] = s["buckets"].get(m, ZERO) + row["amount"]
        s["gl_total"] += row["amount"]
        if period.start <= row["posting_date"] <= period.end:
            s["posted_this_period"] += row["amount"]
        s["row_ids"].append(row["row_id"])
        ctx.row_key[row["row_id"]] = key
    return ctx


def posting_vs_service(rows: list[dict], period: Period) -> list[dict]:
    """Monthly table: GL posted in month vs service-period total for month, plus before/after rows."""
    months = period.fy_month_keys()
    table = {m: {"month": m, "gl_total": ZERO, "service_total": ZERO, "lines_posted": 0, "lines_by_service": 0}
             for m in months}
    before = {"month": f"Service before {months[0]}", "gl_total": ZERO, "service_total": ZERO,
              "lines_posted": 0, "lines_by_service": 0}
    after = {"month": f"Service after {months[-1]}", "gl_total": ZERO, "service_total": ZERO,
             "lines_posted": 0, "lines_by_service": 0}
    for row in rows:
        pm = month_key(row["posting_date"])
        if pm in table:
            table[pm]["gl_total"] += row["amount"]
            table[pm]["lines_posted"] += 1
        sm = row["service_month"]
        target = table.get(sm) or (before if sm < months[0] else after)
        target["service_total"] += row["amount"]
        target["lines_by_service"] += 1
    out = []
    for m in months:
        t = table[m]
        out.append({**t, "variance": t["gl_total"] - t["service_total"], "current": m == period.key})
    for extra in (before, after):
        out.append({**extra, "variance": extra["gl_total"] - extra["service_total"], "current": False})
    return out
