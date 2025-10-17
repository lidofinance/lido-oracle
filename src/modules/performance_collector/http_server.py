from threading import Thread
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request
from waitress import serve
import traceback

from src.modules.performance_collector.db import DutiesDB
from src.modules.performance_collector.codec import EpochBlobCodec
from src import variables


def _parse_from_to(args: Dict[str, Any]) -> Optional[tuple[int, int]]:
    f = args.get("from")
    t = args.get("to")
    if f is None or t is None:
        return None
    try:
        fi = int(f)
        ti = int(t)
    except Exception:
        return None
    if fi > ti:
        return None
    return fi, ti


def _create_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/epochs/check")
    def epochs_check():
        try:
            parsed = _parse_from_to(request.args)
            if not parsed:
                return jsonify({"error": "Invalid or missing 'from'/'to' params"}), 400
            l, r = parsed
            db = DutiesDB(app.config["DB_PATH"])
            result = db.is_range_available(l, r)
            return jsonify({"result": bool(result)})
        except Exception as e:
            return jsonify({"error": repr(e), "trace": traceback.format_exc()}), 500

    @app.get("/epochs/missing")
    def epochs_missing():
        try:
            parsed = _parse_from_to(request.args)
            if not parsed:
                return jsonify({"error": "Invalid or missing 'from'/'to' params"}), 400
            l, r = parsed
            db = DutiesDB(app.config["DB_PATH"])
            result = db.missing_epochs_in(l, r)
            return jsonify({"result": result})
        except Exception as e:
            return jsonify({"error": repr(e), "trace": traceback.format_exc()}), 500
        
    @app.get("/epochs/blob")
    def epochs_blob():
        try:
            parsed = _parse_from_to(request.args)
            if not parsed:
                return jsonify({"error": "Invalid or missing 'from'/'to' params"}), 400
            l, r = parsed
            db = DutiesDB(app.config["DB_PATH"])
            epochs: list[dict[str, Any]] = []
            for e in range(l, r + 1):
                blob = db.get_epoch_blob(e)
                epochs.append({
                    "epoch": e,
                    "blob": blob.hex() if blob is not None else None,
                })
            return jsonify({"result": epochs})
        except Exception as e:
            return jsonify({"error": repr(e), "trace": traceback.format_exc()}), 500

    @app.get("/epochs/<int:epoch>")
    def epoch_details(epoch: int):
        try:
            db = DutiesDB(app.config["DB_PATH"])
            blob = db.get_epoch_blob(epoch)
            if blob is None:
                return jsonify({"error": "epoch not found", "epoch": epoch}), 404

            misses, props, syncs = EpochBlobCodec.decode(blob)

            proposals = [
                {"validator_index": int(p.validator_index), "is_proposed": bool(p.is_proposed)} for p in props
            ]
            sync_misses = [
                {"validator_index": int(s.validator_index), "missed_count": int(s.missed_count)} for s in syncs
            ]

            return jsonify(
                {
                    "epoch": int(epoch),
                    "att_misses": list(misses),
                    "proposals": proposals,
                    "sync_misses": sync_misses,
                }
            )
        except Exception as e:
            return jsonify({"error": repr(e), "trace": traceback.format_exc()}), 500

    return app


def start_performance_api_server(db_path):
    host = "0.0.0.0"
    app = _create_app(db_path)
    t = Thread(target=lambda: serve(app, host=host, port=variables.PERFORMANCE_COLLECTOR_SERVER_API_PORT), daemon=True)
    t.start()
