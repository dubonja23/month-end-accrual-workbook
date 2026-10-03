"""JSON endpoints. The browser only displays what these return; it does no accrual math."""
from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from .engine.backup import build_workbook
from .engine.journal import upload_csv
from .engine.legal import add_vendor_defaults
from .engine.loader import InputError
from .engine.model import jsonable
from .engine.period import Period
from .engine.vendor_opex import ValidationError
from . import datasets
from .runner import DATASET_LABELS, USER, Workbook
from .store import LockedPeriodError, SignOffBlocked

WEB = Path(__file__).resolve().parent / "web"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def create_app(data_dir=None, config_path=None, db_path=None, user_dir=None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    wb = Workbook.remembered(data_dir, config_path, db_path, user_dir)
    app.config["WORKBOOK"] = wb

    def current_period() -> str:
        return wb.current_period()

    def check_period(p: str) -> str:
        Period.parse(p)
        return p

    def body() -> dict:
        return request.get_json(silent=True) or {}

    @app.errorhandler(ValidationError)
    def _validation(e):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(ValueError)
    def _value(e):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(datasets.DatasetError)
    def _dataset(e):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(413)
    def _too_big(e):
        return jsonify({"error": "File is larger than 25 MB."}), 413

    @app.errorhandler(LockedPeriodError)
    def _locked(e):
        return jsonify({"error": str(e)}), 423

    @app.errorhandler(SignOffBlocked)
    def _blocked(e):
        return jsonify({"error": str(e)}), 409

    @app.errorhandler(InputError)
    def _input(e):
        return jsonify({"error": f"Input data problem: {e}"}), 500

    # ---------- static ----------
    @app.get("/")
    def index():
        return send_from_directory(WEB, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(WEB, name)

    # ---------- read ----------
    @app.get("/api/meta")
    def meta():
        cur = Period.parse(current_period())
        periods = [Period(cur.year, m).key for m in range(cur.month, 0, -1)]
        return jsonify(jsonable({"company": wb.cfg["company"], "user": wb.user, "current_period": cur.key,
                                 "dataset": wb.dataset, "dataset_label": DATASET_LABELS[wb.dataset],
                                 "periods": periods, "signoffs": wb.store.signoffs(),
                                 "legal_defaults": add_vendor_defaults(wb.cfg),
                                 "data_issues": sum(1 for c in datasets.cross_checks(wb.inputs, wb.cfg, cur.key)
                                                    if c["level"] in ("error", "warning"))}))

    @app.get("/api/period/<p>")
    def period_result(p):
        res = wb.run(check_period(p))
        items = wb.store.attention()
        open_vendors = {i["vendor_id"] for i in items if i["period"] == p and i["status"] != "Resolved"
                        and i["vendor_id"]}
        for row in res["mom"]["rows"]:
            row["needs_attention"] = row["vendor_id"] in open_vendors
        res.pop("attention_candidates", None)
        res["attention_items"] = items
        res["is_current_period"] = p == current_period()
        return jsonify(jsonable(res))

    @app.get("/api/period/<p>/override-log")
    def override_log(p):
        return jsonify(jsonable(wb.store.override_log(check_period(p), request.args.get("key", ""))))

    @app.get("/api/period/<p>/je.csv")
    def je_csv(p):
        saved = wb.store.signoff(check_period(p))
        text = saved["je_csv"] if saved else upload_csv(wb.run(p)["je"])
        return Response(text, mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=je_upload_{p.replace('-', '')}.csv"})

    @app.get("/api/period/<p>/backup.xlsx")
    def backup(p):
        saved = wb.store.signoff(check_period(p))
        data = saved["backup"] if saved else build_workbook(wb.run(p))
        return Response(data, mimetype=XLSX,
                        headers={"Content-Disposition": f"attachment; filename=je_backup_{p.replace('-', '')}.xlsx"})

    @app.get("/api/history/<p>")
    def history(p):
        saved = wb.store.signoff(check_period(p))
        if not saved:
            return jsonify({"error": f"{p} is not signed off."}), 404
        return jsonify(jsonable({k: v for k, v in saved.items() if k not in ("je_csv", "backup")}))

    # ---------- edits (each returns {"ok": true}; the page then re-fetches the period) ----------
    def ok(**extra):
        return jsonify({"ok": True, **jsonable(extra)})

    @app.post("/api/period/<p>/override")
    def set_override(p):
        b = body()
        wb.store.set_override(check_period(p), b.get("key", ""), b.get("amount"), b.get("explanation"), wb.user)
        return ok()

    @app.post("/api/period/<p>/override/remove")
    def remove_override(p):
        b = body()
        wb.store.remove_override(check_period(p), b.get("key", ""), b.get("explanation"), wb.user)
        return ok()

    @app.post("/api/period/<p>/manual")
    def add_manual(p):
        entry = {**body(), "period": check_period(p)}
        new_id = wb.store.add_manual(entry, wb.user, wb.roster_vendor_ids, current_period())
        return ok(id=new_id)

    @app.delete("/api/period/<p>/manual/<int:manual_id>")
    def delete_manual(p, manual_id):
        wb.store.delete_manual(check_period(p), manual_id)
        return ok()

    @app.post("/api/period/<p>/legal/<vendor_id>")
    def save_legal(p, vendor_id):
        b = body()
        wb.store.save_legal(check_period(p), vendor_id, b.get("fields") or {}, wb.user, b.get("splits"))
        return ok()

    @app.post("/api/period/<p>/legal-add")
    def add_legal(p):
        row = {**add_vendor_defaults(wb.cfg), **{k: v for k, v in body().items() if v not in (None, "")}}
        return ok(id=wb.store.add_legal_vendor(check_period(p), row, wb.user))

    @app.post("/api/period/<p>/standing/confirm")
    def confirm_standing(p):
        wb.store.confirm_standing(check_period(p), body().get("key", ""), wb.user)
        return ok()

    @app.post("/api/period/<p>/mom/review")
    def mom_review(p):
        b = body()
        wb.store.set_reviewed(check_period(p), b.get("key", ""), bool(b.get("reviewed")), wb.user)
        return ok()

    @app.post("/api/period/<p>/component")
    def component(p):
        b = body()
        wb.store.set_component(check_period(p), b.get("component", ""), bool(b.get("complete")), wb.user)
        return ok()

    @app.post("/api/period/<p>/attention")
    def add_attention(p):
        return ok(id=wb.store.add_attention(check_period(p), body(), wb.user))

    @app.patch("/api/period/<p>/attention/<int:item_id>")
    def update_attention(p, item_id):
        wb.store.update_attention(check_period(p), item_id, body(), wb.user)
        return ok()

    @app.post("/api/period/<p>/rollover")
    def rollover(p):
        return ok(**wb.rollover(check_period(p)))

    @app.post("/api/period/<p>/signoff")
    def sign_off(p):
        res = wb.run(check_period(p))
        wb.store.sign_off(p, res, wb.user, upload_csv(res["je"]), build_workbook(res))
        return ok()

    # ---------- settings: data sets and uploads ----------
    def require_user_dataset():
        if wb.dataset != USER:
            raise datasets.DatasetError("Sample data is read-only. Switch to My data to upload your own files.")

    @app.get("/api/settings")
    def settings():
        rules = datasets.read_rules(wb.data_dir) if wb.dataset == USER else {}
        return jsonify(jsonable({
            "dataset": wb.dataset, "datasets": [{"id": k, "label": v} for k, v in DATASET_LABELS.items()],
            "files": datasets.file_status(wb.data_dir),
            "general": {"company": wb.cfg["company"], "current_period": current_period(), "user": wb.user},
            "inputs_meta": {**wb.inputs.capex_meta, "prior_period": wb.inputs.prior_je_meta.get("period"),
                            "reversed_total": wb.inputs.prior_je_meta.get("reversed_total")},
            "rules_summary": {k: (len(v) if isinstance(v, list) else None) for k, v in rules.items()},
            "checks": datasets.cross_checks(wb.inputs, wb.cfg, current_period()),
            "prior_source": wb.inputs_for(current_period())[1],
            "user_dir": str(wb.user_dir),
        }))

    @app.post("/api/settings/dataset")
    def set_dataset():
        wb.activate(body().get("dataset", ""), remember=True)
        return ok(dataset=wb.dataset)

    @app.get("/api/settings/template/<name>")
    def template(name):
        return Response(datasets.template_csv(name), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=template_{name}"})

    @app.get("/api/settings/example/<name>")
    def example(name):
        if name not in datasets.FILE_NAMES:
            raise datasets.DatasetError(f"Unknown file {name!r}.")
        return send_from_directory(wb.sample_paths[0], name, as_attachment=True, download_name=f"example_{name}")

    @app.get("/api/settings/file/<name>")
    def current_file(name):
        if name not in datasets.FILE_NAMES + ["rules.yaml"]:
            raise datasets.DatasetError(f"Unknown file {name!r}.")
        folder = wb.data_dir if name != "rules.yaml" else wb.config_path.parent
        return send_from_directory(folder, name if name != "rules.yaml" else wb.config_path.name, as_attachment=True)

    @app.post("/api/settings/upload/<name>")
    def upload(name):
        require_user_dataset()
        f = request.files.get("file")
        if not f:
            raise datasets.DatasetError("Choose a CSV file to upload.")
        rows = datasets.validate_and_save(wb.data_dir, name, f.read())
        wb.reload()
        return ok(rows=rows)

    @app.post("/api/settings/rules")
    def upload_rules():
        require_user_dataset()
        f = request.files.get("file")
        if not f:
            raise datasets.DatasetError("Choose a rules.yaml file to upload.")
        datasets.save_rules_upload(wb.data_dir, f.read())
        wb.reload()
        return ok()

    @app.post("/api/settings/general")
    def save_general():
        require_user_dataset()
        b = body()
        datasets.save_general(wb.data_dir, b.get("company"), b.get("current_period"))
        wb.reload()
        return ok()

    @app.post("/api/settings/inputs-meta")
    def save_inputs_meta():
        require_user_dataset()
        datasets.save_inputs_meta(wb.data_dir, body())
        wb.reload()
        return ok()

    @app.post("/api/settings/reset")
    def reset_user_data():
        require_user_dataset()
        if body().get("confirm") != "RESET":
            raise datasets.DatasetError("Type RESET to confirm.")
        wb.store.db.close()
        wb.store = None
        datasets.reset_user_folder(wb.user_dir, wb.sample_paths[1])
        wb.activate(USER)
        return ok()

    return app
