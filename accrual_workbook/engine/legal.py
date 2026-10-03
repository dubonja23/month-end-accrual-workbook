"""Legal accrual lines, edits and splits.

Reading legal backup documents with AI is intentionally left out of this rebuild; see
`read_backup_document` below and the README.
"""
from __future__ import annotations

from .money import ZERO, D, r2
from .vendor_opex import ValidationError

EDITABLE = ("amount", "gl", "item", "customer", "project", "dept", "location", "note")


def _gl_ok(value) -> bool:
    text = str(value or "").strip()
    return text.isdigit() and len(text) == 5


def validate_legal_edit(fields: dict) -> None:
    if "amount" in fields:
        try:
            D(fields["amount"])
        except ValueError as exc:
            raise ValidationError("Legal amount must be a number.") from exc
    if "gl" in fields and not _gl_ok(fields["gl"]):
        raise ValidationError("GL must be 5 digits.")


def validate_split(lines: list[dict]) -> None:
    if len(lines) < 2:
        raise ValidationError("A split needs at least 2 lines.")
    for i, ln in enumerate(lines, 1):
        if not _gl_ok(ln.get("gl")):
            raise ValidationError(f"Split line {i}: GL must be 5 digits.")
        try:
            D(ln.get("amount"))
        except ValueError as exc:
            raise ValidationError(f"Split line {i}: amount must be a number.") from exc


def build(legal_rows: list[dict], cfg: dict, state) -> dict:
    default_gl = int(cfg["legal"]["default_gl"])
    edits = getattr(state, "legal_edits", {}) or {}
    added = getattr(state, "legal_added", []) or []
    rows = []
    sources = [(r, False) for r in legal_rows] + [(a, True) for a in added]
    for base, is_added in sources:
        row = {
            "vendor": base["vendor"], "vendor_id": base["vendor_id"], "amount": D(base.get("amount")),
            "gl": int(base.get("gl") or default_gl), "item": base.get("item", ""),
            "customer": base.get("customer", ""), "project": base.get("project", ""),
            "dept": base.get("dept", ""), "location": base.get("location", ""), "note": base.get("note", ""),
            "added": is_added, "edited": False, "splits": None,
        }
        e = edits.get(row["vendor_id"])
        if e:
            for f in EDITABLE:
                if f in e and e[f] is not None:
                    row[f] = D(e[f]) if f == "amount" else (int(e[f]) if f == "gl" else e[f])
            row["edited"] = True
            if e.get("splits"):
                row["splits"] = [{"amount": r2(D(s["amount"])), "gl": int(s["gl"]), "item": s.get("item", "") or row["item"],
                                  "note": s.get("note", "")} for s in e["splits"]]
        if row["splits"]:
            row["total"] = sum((s["amount"] for s in row["splits"]), ZERO)
            row["amount"] = row["total"]
            row["je_lines"] = row["splits"]
        else:
            row["total"] = r2(row["amount"])
            row["je_lines"] = [{"amount": row["total"], "gl": row["gl"], "item": row["item"], "note": row["note"]}]
        rows.append(row)
    return {"rows": rows, "total": sum((r["total"] for r in rows), ZERO)}


def add_vendor_defaults(cfg: dict) -> dict:
    return dict(cfg["legal"].get("add_vendor_defaults") or {})


def read_backup_document(path: str) -> dict:  # pragma: no cover - documented stub
    """STUB (not implemented in the portfolio rebuild).

    How it would work: a reviewer attaches a law firm's invoice or WIP estimate, an AI model reads it and
    proposes the accrual amount, matter (project) and customer for the row, and the reviewer accepts or
    edits the proposal before saving. It would never save on its own.
    """
    raise NotImplementedError("AI reading of legal backup is not part of this rebuild.")
