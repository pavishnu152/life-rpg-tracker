from datetime import date

from flask import Blueprint, current_app, jsonify, request, send_from_directory

from models import (
    get_daily_score,
    get_history,
    get_stats,
    get_today_habits,
    set_habit_completion,
)


api_bp = Blueprint("api", __name__)


@api_bp.get("/habits/today")
def habits_today():
    requested_date = request.args.get("date") or date.today().isoformat()
    return jsonify(get_today_habits(requested_date))


@api_bp.post("/habits/complete")
def habits_complete():
    data = request.get_json(silent=True) or {}
    habit_id = data.get("habit_id")
    completed = bool(data.get("completed", False))
    day = data.get("date") or date.today().isoformat()

    if not isinstance(habit_id, int):
        return jsonify({"error": "habit_id must be an integer"}), 400

    set_habit_completion(habit_id=habit_id, completed=completed, target_date=day)
    return jsonify(
        {
            "message": "Habit state updated.",
            "today": get_today_habits(day),
            "stats": get_stats(),
        }
    )


@api_bp.get("/stats")
def stats():
    return jsonify(get_stats())


@api_bp.get("/history")
def history():
    is_browser_navigation = request.headers.get("Sec-Fetch-Dest") == "document"
    if is_browser_navigation:
        build_root = current_app.config["REACT_BUILD_ROOT"]
        return send_from_directory(build_root, "index.html")

    return jsonify(get_history())


@api_bp.get("/score/today")
def score_today():
    requested_date = request.args.get("date") or date.today().isoformat()
    return jsonify(get_daily_score(requested_date))
