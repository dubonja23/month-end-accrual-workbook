"""Command line: `python -m accrual_workbook run --period 2026-09 --out out/` or `serve`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine.backup import build_workbook
from .engine.journal import upload_csv
from .engine.model import jsonable
from .runner import Workbook


def cmd_run(args) -> int:
    wb = Workbook(args.data, args.config, args.db, args.user_dir, dataset=args.dataset)
    result = wb.run(args.period)
    je = result["je"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = args.period.replace("-", "")
    (out / f"je_upload_{tag}.csv").write_text(upload_csv(je), encoding="utf-8")
    (out / f"je_backup_{tag}.xlsx").write_bytes(build_workbook(result))
    summary = {
        "company": result["company"], "period": result["period"], "totals": result["totals"],
        "je": {"lines": len(je["lines"]), "debits": je["total_debits"], "credits": je["total_credits"],
               "memo": je["header"]["memo"]},
        "checks": je["checks"], "scope_exclusions": result["scope"]["counts"],
        "capex_not_final": result["capex"]["not_final"], "checklist": result["checklist"],
    }
    (out / f"summary_{tag}.json").write_text(json.dumps(jsonable(summary), indent=2), encoding="utf-8")

    t = result["totals"]
    print(f"{result['company']} - {result['period_label']} accrual")
    print(f"  Vendor OpEx     {t['vendor_opex']:>14,.2f}")
    print(f"  Legal           {t['legal']:>14,.2f}")
    print(f"  Capex Projects  {t['capex']:>14,.2f}")
    print(f"  Total           {t['total']:>14,.2f}")
    print(f"  JE: {len(je['lines'])} lines, debits {je['total_debits']:,.2f}, credits {je['total_credits']:,.2f}")
    for c in je["checks"]:
        print(f"  [{'OK' if c['ok'] else 'FAIL'}] {c['name']}  (diff {c['difference']:,.2f})")
    print(f"  Wrote {out}")
    if not je["ok"]:
        print("JE tie-out check failed.", file=sys.stderr)
        return 1
    return 0


def cmd_serve(args) -> int:
    from .api import create_app
    app = create_app(args.data, args.config, args.db, args.user_dir)
    app.run(host="127.0.0.1", port=args.port, debug=False)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="accrual_workbook")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "serve"):
        sp = sub.add_parser(name)
        sp.add_argument("--data", default=None, help="input CSV folder (default data/sample)")
        sp.add_argument("--config", default=None, help="rules.yaml path")
        sp.add_argument("--db", default=None, help="SQLite path (default data/workbook.db)")
        sp.add_argument("--user-dir", default=None, help="folder for your own data (default data/user)")
        if name == "run":
            sp.add_argument("--period", required=True)
            sp.add_argument("--dataset", choices=["sample", "user"], default="sample",
                            help="sample data or your own data uploaded on the Settings tab")
            sp.add_argument("--out", default="out")
        else:
            sp.add_argument("--port", type=int, default=5000)
    args = p.parse_args(argv)
    return cmd_run(args) if args.cmd == "run" else cmd_serve(args)
