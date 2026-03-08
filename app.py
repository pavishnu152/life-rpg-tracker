import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from models import init_db
from routes.api import api_bp


def create_app() -> Flask:
    backend_dir = Path(__file__).resolve().parent
    react_build_root = backend_dir / "static"
    react_assets_dir = react_build_root / "static"

    app = Flask(__name__, static_folder=str(react_assets_dir), static_url_path="/static")
    app.config["REACT_BUILD_ROOT"] = str(react_build_root)
    app.config["JSON_SORT_KEYS"] = False

    cors_origins = os.getenv("CORS_ORIGINS", "*")
    CORS(
        app,
        resources={
            r"/habits/*": {"origins": cors_origins},
            r"/stats": {"origins": cors_origins},
            r"/history": {"origins": cors_origins},
            r"/score/*": {"origins": cors_origins},
        },
    )

    app.register_blueprint(api_bp)
    register_error_handlers(app)
    register_spa_routes(app)

    init_db()
    return app


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def handle_404(_error):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(500)
    def handle_500(_error):
        return jsonify({"error": "Internal server error"}), 500


def register_spa_routes(app: Flask) -> None:
    build_root = Path(app.config["REACT_BUILD_ROOT"])

    def serve_react_app():
        return send_from_directory(str(build_root), "index.html")

    @app.get("/")
    def root():
        return serve_react_app()

    @app.get("/<path:path>")
    def spa_fallback(path: str):
        if path.startswith("habits/") or path.startswith("score/") or path in {"stats", "history"}:
            return jsonify({"error": "Resource not found"}), 404

        target = build_root / path
        if target.exists() and target.is_file():
            return send_from_directory(str(build_root), path)

        return serve_react_app()


app = create_app()


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "0") == "1"
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
