from functools import wraps
from threading import Thread
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request
from waitress import serve
import traceback

from src.modules.performance_collector.db import DutiesDB
from src.modules.performance_collector.codec import EpochDataCodec
from src import variables


def _parse_from_to(args: Dict[str, Any]) -> Optional[tuple[int, int]]:
    f = args.get("from")
    t = args.get("to")
    if f is None or t is None:
        return None
    fi = int(f)
    ti = int(t)
    if fi > ti:
        return None
    return fi, ti


def _create_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    _register_health_route(app)
    _register_epoch_range_routes(app)
    _register_epoch_blob_routes(app)
    _register_debug_routes(app)
    _register_demand_routes(app)

    return app


def _register_health_route(app: Flask) -> None:
    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})


def _register_epoch_range_routes(app: Flask) -> None:
    @app.get("/epochs/check")
    @_with_error_handling
    def epochs_check():
        l_epoch, r_epoch = _require_epoch_range(request.args)
        db = _db(app)
        return jsonify({"result": bool(db.is_range_available(l_epoch, r_epoch))})

    @app.get("/epochs/missing")
    @_with_error_handling
    def epochs_missing():
        l_epoch, r_epoch = _require_epoch_range(request.args)
        db = _db(app)
        return jsonify({"result": db.missing_epochs_in(l_epoch, r_epoch)})


def _register_epoch_blob_routes(app: Flask) -> None:
    @app.get("/epochs/blob")
    @_with_error_handling
    def epochs_blob():
        l_epoch, r_epoch = _require_epoch_range(request.args)
        db = _db(app)
        epochs: list[str | None] = []
        for epoch in range(l_epoch, r_epoch + 1):
            blob = db.get_epoch_blob(epoch)
            epochs.append(blob.hex() if blob is not None else None)
        return jsonify({"result": epochs})

    @app.get("/epochs/blob/<int:epoch>")
    @_with_error_handling
    def epoch_blob(epoch: int):
        db = _db(app)
        blob = db.get_epoch_blob(epoch)
        return jsonify({"result": blob.hex() if blob is not None else None})


def _register_debug_routes(app: Flask) -> None:
    @app.get("/debug/epochs/<int:epoch>")
    @_with_error_handling
    def debug_epoch_details(epoch: int):
        db = _db(app)
        blob = db.get_epoch_blob(epoch)
        if blob is None:
            return jsonify({"error": "epoch not found", "epoch": epoch}), 404

        misses, props, syncs = EpochDataCodec.decode(blob)

        proposals = [{"validator_index": int(p.validator_index), "is_proposed": bool(p.is_proposed)} for p in props]
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


def _register_demand_routes(app: Flask) -> None:
    @app.post("/epochs/demand")
    @_with_error_handling
    def set_epochs_demand():
        data = _require_json(request.get_json(), {"consumer", "l_epoch", "r_epoch"})
        _validate_epoch_bounds(data["l_epoch"], data["r_epoch"])

        db = _db(app)
        db.store_demand(data["consumer"], data["l_epoch"], data["r_epoch"])

        return jsonify({"status": "ok", "consumer": data["consumer"], "l_epoch": data["l_epoch"], "r_epoch": data["r_epoch"]})

    @app.get("/epochs/demand")
    @_with_error_handling
    def get_epochs_demand():
        db = _db(app)
        return jsonify({"result": db.epochs_demand()})


def _db(app: Flask) -> DutiesDB:
    return DutiesDB(app.config["DB_PATH"])


def _require_epoch_range(args: Dict[str, Any]) -> tuple[int, int]:
    parsed = _parse_from_to(args)
    if not parsed:
        raise ValueError("Invalid or missing 'from'/'to' params")
    return parsed


def _require_json(data: Optional[Dict[str, Any]], required: set[str]) -> Dict[str, Any]:
    if not data:
        raise ValueError(f"Missing JSON body or required fields: {', '.join(sorted(required))}")
    missing = required.difference(data)
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(sorted(missing))}")
    return data


def _validate_epoch_bounds(l_epoch: Any, r_epoch: Any) -> None:
    if not isinstance(l_epoch, int) or not isinstance(r_epoch, int) or l_epoch > r_epoch:
        raise ValueError("'l_epoch' and 'r_epoch' must be integers, and 'l_epoch' <= 'r_epoch'")


def _with_error_handling(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return jsonify({"error": repr(exc), "trace": traceback.format_exc()}), 500

    return wrapper


def start_performance_api_server(db_path):
    host = "0.0.0.0"
    app = _create_app(db_path)
    t = Thread(target=lambda: serve(app, host=host, port=variables.PERFORMANCE_COLLECTOR_SERVER_API_PORT), daemon=True)
    t.start()
