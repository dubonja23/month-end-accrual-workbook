"""Journal entry build, dimensions, tie-out checks and the JE upload export."""
from __future__ import annotations

import csv
import io

from .config import key_of
from .money import ZERO, D, r2
from .period import Period

SECTION_OPEX = "Vendor OpEx"
SECTION_LEGAL = "Legal"
SECTION_CAPEX = "Capex Projects"
SECTIONS = [SECTION_OPEX, SECTION_LEGAL, SECTION_CAPEX]

UPLOAD_COLUMNS = ["JOURNAL", "DATE", "REVERSEDATE", "DESCRIPTION", "REFERENCE_NO", "LINE_NO", "ACCT_NO",
                  "LOCATION_ID", "DEPT_ID", "DOCUMENT", "MEMO", "DEBIT", "CREDIT", "CUSTOMERID", "PROJECTID",
                  "VENDORID", "ITEMID"]


# ---------- dimensions ----------

def build_dims_context(je_dims: list[dict], scoped_rows: list[dict], dim_names: dict) -> dict:
    by_key: dict = {}
    for d in je_dims:
        k = key_of(d["vendor_id"], d["gl_account"])
        cur = by_key.get(k)
        # last month's JE beats the most recent bill
        if cur is None or (cur["source"] != "prior_je" and d["source"] == "prior_je"):
            by_key[k] = d
    name_to_id = {t: {v: k for k, v in m.items()} for t, m in dim_names.items()}
    latest: dict = {}
    for r in scoped_rows:
        if r["amount"] <= 0:
            continue
        cur = latest.get(r["vendor_id"])
        if cur is None or r["posting_date"] > cur["posting_date"]:
            latest[r["vendor_id"]] = r
    return {"by_key": by_key, "latest_bill": latest, "name_to_id": name_to_id}


def resolve_dims(line: dict, ctx: dict) -> dict:
    """Dims from last month's JE for the same vendor + account, else the vendor's most recent bill."""
    if line.get("manual_dims"):
        d = line["manual_dims"]
        out = {"dept": d.get("dept", ""), "location": d.get("location", ""), "item": d.get("item", ""),
               "source": "manual add"}
    else:
        k = key_of(line["vendor_id"], line["gl_account"])
        d = ctx["by_key"].get(k)
        if d:
            out = {"dept": d["dept"], "location": d["location"], "item": d["item"], "source": d["source"]}
        else:
            bill = ctx["latest_bill"].get(line["vendor_id"])
            if bill:
                ids = ctx["name_to_id"]
                out = {"dept": ids.get("dept", {}).get(bill["department_name"], ""),
                       "location": ids.get("location", {}).get(bill["location_name"], ""),
                       "item": "", "source": "latest_bill"}
            else:
                out = {"dept": "", "location": "", "item": "", "source": "none"}
    out["missing"] = [f for f in ("dept", "location") if not out[f]]
    return out


def dept_split(amount, shares: list[dict]) -> list[tuple[str, object]]:
    """Split an amount across departments by share. A rounding difference (at most one cent per part)
    goes to the first part. A larger difference means the shares are wrong and is left in place so the
    tie-out check fails visibly."""
    amount = D(amount)
    parts = [(s["dept"], r2(amount * D(str(s["share"])))) for s in shares]
    diff = amount - sum((p[1] for p in parts), ZERO)
    if diff != 0 and abs(diff) <= D("0.01") * len(parts):
        parts[0] = (parts[0][0], parts[0][1] + diff)
    return parts


# ---------- build ----------

def _names(dim_names: dict, kind: str, ident) -> str:
    return dim_names.get(kind, {}).get(str(ident), "") if ident not in (None, "") else ""


def build(period: Period, opex_lines: list[dict], legal: dict, capex: dict, cfg: dict, dim_names: dict) -> dict:
    je_cfg = cfg["je"]
    credit_acct = int(je_cfg["accrued_expenses_account"])
    memo = f"OPEX - Accruals - {period.memo_tag}"
    splits = {f"{s['vendor_id']}|{int(s['gl_account'])}": s["shares"] for s in je_cfg.get("dept_splits") or []}

    debits: dict[str, list[dict]] = {s: [] for s in SECTIONS}

    def debit(section, acct, amount, dims, line_memo, source, ref):
        debits[section].append({
            "section": section, "acct": int(acct), "debit": r2(amount),
            "dept": dims.get("dept", ""), "location": dims.get("location", ""),
            "project": dims.get("project", ""), "customer": dims.get("customer", ""),
            "vendor_id": dims.get("vendor_id", ""), "vendor_name": dims.get("vendor_name", ""),
            "item": dims.get("item", ""), "memo": line_memo, "dims_source": source, "ref": ref,
            "missing_dims": [f for f in ("dept", "location") if not dims.get(f)],
        })

    for ln in opex_lines:
        if ln["final_accrual"] <= 0:
            continue
        d = ln["dims"]
        base = {"dept": d["dept"], "location": d["location"], "item": d["item"],
                "vendor_id": ln["vendor_id"], "vendor_name": ln["vendor_name"]}
        line_memo = f"Accrual - {ln['vendor_name']} - {ln['gl_account']}"
        shares = splits.get(ln["key"])
        if shares:
            for dept, amt in dept_split(ln["final_accrual"], shares):
                debit(SECTION_OPEX, ln["gl_account"], amt, {**base, "dept": dept}, line_memo,
                      f"{d['source']} (dept split)", ln["key"])
        else:
            debit(SECTION_OPEX, ln["gl_account"], ln["final_accrual"], base, line_memo, d["source"], ln["key"])

    for row in legal["rows"]:
        for i, jl in enumerate(row["je_lines"]):
            if jl["amount"] == 0:
                continue
            dims = {"dept": row["dept"], "location": row["location"], "project": row["project"],
                    "customer": row["customer"], "vendor_id": row["vendor_id"], "vendor_name": row["vendor"],
                    "item": jl["item"]}
            label = f"Legal accrual - {row['vendor']}" + (f" (split {i + 1})" if row["splits"] else "")
            debit(SECTION_LEGAL, jl["gl"], jl["amount"], dims, label, "legal tab", row["vendor_id"])

    cx = cfg["capex"]
    for g in capex["groups"]:
        if g["je_amount"] <= 0:
            continue
        dims = {"dept": cx.get("dept", ""), "location": g["location_id"], "project": g["project_id"],
                "customer": cx.get("customer", ""), "vendor_id": g["vendor_id"], "vendor_name": g["vendor"],
                "item": cx.get("item", "")}
        debit(SECTION_CAPEX, cx["accrual_account"], g["je_amount"], dims,
              f"Capex accrual - {g['deal']} - {g['vendor']}", "capex config", f"{g['project_id']}|{g['vendor_id']}")

    lines = []
    for section in SECTIONS:
        ordered = sorted(debits[section], key=lambda x: (x["debit"], x["acct"], x["vendor_id"], x["dept"]))
        for dl in ordered:
            lines.append({**dl, "side": "debit", "credit": ZERO})
        for dl in ordered:
            lines.append({**dl, "side": "credit", "acct": credit_acct, "credit": dl["debit"], "debit": ZERO})
    for i, ln in enumerate(lines, 1):
        ln["line_no"] = i
        ln["acct_name"] = _names(dim_names, "account", ln["acct"])
        ln["dept_name"] = _names(dim_names, "dept", ln["dept"])
        ln["location_name"] = _names(dim_names, "location", ln["location"])
        ln["project_name"] = _names(dim_names, "project", ln["project"])
        ln["customer_name"] = _names(dim_names, "customer", ln["customer"])
        ln["item_name"] = _names(dim_names, "item", ln["item"])

    header = {
        "memo": memo, "date": period.end, "reverse_date": period.reverse_date,
        "journal": je_cfg["journal"], "reference": f"{je_cfg['reference_prefix']}-{period.year}{period.month:02d}",
    }
    opex_tab = sum((ln["final_accrual"] for ln in opex_lines), ZERO)
    checks = tie_out(lines, opex_tab, legal["total"], capex["total"])
    return {"header": header, "lines": lines, "checks": checks, "ok": all(c["ok"] for c in checks),
            "total_debits": sum((ln["debit"] for ln in lines), ZERO),
            "total_credits": sum((ln["credit"] for ln in lines), ZERO)}


def section_debits(lines: list[dict], section: str):
    return sum((ln["debit"] for ln in lines if ln["section"] == section), ZERO)


def tie_out(lines: list[dict], opex_tab, legal_tab, capex_tab) -> list[dict]:
    debits = sum((ln["debit"] for ln in lines), ZERO)
    credits = sum((ln["credit"] for ln in lines), ZERO)

    def check(name, actual, expected):
        return {"name": name, "actual": actual, "expected": expected, "difference": actual - expected,
                "ok": actual == expected}

    return [
        check("Debits = Credits", debits, credits),
        check("Vendor OpEx = Tab 2", section_debits(lines, SECTION_OPEX), D(opex_tab)),
        check("Legal = Tab 3", section_debits(lines, SECTION_LEGAL), D(legal_tab)),
        check("Capex = Tab 4", section_debits(lines, SECTION_CAPEX), D(capex_tab)),
    ]


def debit_credit_pairs_match(lines: list[dict]) -> bool:
    """Every debit has a matching credit to accrued expenses with identical dimensions, same order."""
    dims = ("dept", "location", "project", "customer", "vendor_id", "item")
    for section in SECTIONS:
        sec = [ln for ln in lines if ln["section"] == section]
        dr = [ln for ln in sec if ln["side"] == "debit"]
        cr = [ln for ln in sec if ln["side"] == "credit"]
        if len(dr) != len(cr):
            return False
        for a, b in zip(dr, cr):
            if a["debit"] != b["credit"] or any(a[f] != b[f] for f in dims):
                return False
    return True


def upload_csv(je: dict) -> str:
    h = je["header"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(UPLOAD_COLUMNS)
    for ln in je["lines"]:
        w.writerow([
            h["journal"], h["date"].strftime("%m/%d/%Y"), h["reverse_date"].strftime("%m/%d/%Y"), h["memo"],
            h["reference"], ln["line_no"], ln["acct"], ln["location"], ln["dept"], "", ln["memo"],
            f"{ln['debit']:.2f}" if ln["debit"] else "", f"{ln['credit']:.2f}" if ln["credit"] else "",
            ln["customer"], ln["project"], ln["vendor_id"], ln["item"],
        ])
    return buf.getvalue()
