from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"


@dataclass(frozen=True)
class HabitSeed:
    name: str
    category: str
    xp_reward: int
    icon: str


HABIT_SEEDS = [
    HabitSeed("Wake up 5 AM", "Morning Routine", 20, "sunrise"),
    HabitSeed("Fresh up", "Morning Routine", 5, "droplets"),
    HabitSeed("Exercise", "Health", 20, "dumbbell"),
    HabitSeed("Bath", "Morning Routine", 5, "shower-head"),
    HabitSeed("Meditation", "Health", 10, "sparkles"),
    HabitSeed("Write mantra", "Study", 10, "pen"),
    HabitSeed("Breakfast 8:30 AM", "Morning Routine", 5, "coffee"),
    HabitSeed("Learning 9-11 AM", "Study", 20, "book-open"),
    HabitSeed("Institute 11:30-1:30 PM", "Study", 20, "school"),
    HabitSeed("Lunch 2 PM", "Health", 5, "utensils"),
    HabitSeed("Rest", "Health", 5, "moon-star"),
    HabitSeed("Learning 5-8 PM", "Study", 20, "brain"),
    HabitSeed("Family time 8 PM", "Evening", 10, "users"),
    HabitSeed("Dinner 8:30 PM", "Evening", 5, "pizza"),
    HabitSeed("Journal", "Night", 10, "notebook-pen"),
    HabitSeed("Communication practice 9-10 PM", "Night", 10, "message-circle"),
    HabitSeed("Sleep 10 PM", "Health", 20, "bed"),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.touch(exist_ok=True)
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                total_xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                current_streak INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                xp_reward INTEGER NOT NULL,
                icon TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS habit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                habit_id INTEGER NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(date, habit_id),
                FOREIGN KEY(habit_id) REFERENCES habits(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                score REAL NOT NULL,
                completed_count INTEGER NOT NULL,
                total_count INTEGER NOT NULL,
                xp_earned INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    seed_habits()
    seed_user()
    sync_daily_scores()
    refresh_user_stats()


def seed_habits() -> None:
    with get_connection() as conn:
        for habit in HABIT_SEEDS:
            conn.execute(
                """
                INSERT INTO habits (name, category, xp_reward, icon)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    category=excluded.category,
                    xp_reward=excluded.xp_reward,
                    icon=excluded.icon
                """,
                (habit.name, habit.category, habit.xp_reward, habit.icon),
            )
        conn.commit()


def seed_user() -> None:
    with get_connection() as conn:
        user_exists = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        if not user_exists:
            conn.execute(
                """
                INSERT INTO users (name, total_xp, level, current_streak)
                VALUES (?, 0, 1, 0)
                """,
                ("Player One",),
            )
            conn.commit()


def get_today_habits(target_date: str | None = None) -> dict:
    day = target_date or date.today().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                h.id,
                h.name,
                h.category,
                h.xp_reward,
                h.icon,
                COALESCE(hl.completed, 0) AS completed
            FROM habits h
            LEFT JOIN habit_logs hl
              ON h.id = hl.habit_id AND hl.date = ?
            ORDER BY
              CASE h.category
                WHEN 'Morning Routine' THEN 1
                WHEN 'Health' THEN 2
                WHEN 'Study' THEN 3
                WHEN 'Evening' THEN 4
                WHEN 'Night' THEN 5
                ELSE 6
              END,
              h.id
            """,
            (day,),
        ).fetchall()

    habits = [dict(row) for row in rows]
    total = len(habits)
    completed = sum(1 for h in habits if h["completed"] == 1)
    earned_xp = sum(h["xp_reward"] for h in habits if h["completed"] == 1)
    progress_percent = round((completed / total) * 100, 2) if total else 0.0

    return {
        "date": day,
        "habits": habits,
        "progress_percent": progress_percent,
        "completed_count": completed,
        "total_count": total,
        "earned_xp_today": earned_xp,
        "discipline_score": progress_percent,
    }


def set_habit_completion(habit_id: int, completed: bool, target_date: str | None = None) -> None:
    day = target_date or date.today().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO habit_logs (date, habit_id, completed)
            VALUES (?, ?, ?)
            ON CONFLICT(date, habit_id)
            DO UPDATE SET completed=excluded.completed
            """,
            (day, habit_id, 1 if completed else 0),
        )
        conn.commit()

    upsert_daily_score(day)
    refresh_user_stats()


def compute_total_xp() -> int:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(h.xp_reward), 0) AS total_xp
            FROM habit_logs hl
            JOIN habits h ON h.id = hl.habit_id
            WHERE hl.completed = 1
            """
        ).fetchone()
    return int(row["total_xp"]) if row else 0


def compute_current_streak() -> int:
    """
    A streak day is a day with at least one completed habit.
    """
    with get_connection() as conn:
        date_rows = conn.execute(
            """
            SELECT date
            FROM habit_logs
            WHERE completed = 1
            GROUP BY date
            ORDER BY date DESC
            """
        ).fetchall()

    if not date_rows:
        return 0

    completed_dates = {row["date"] for row in date_rows}
    streak = 0
    cursor = date.today()

    while cursor.isoformat() in completed_dates:
        streak += 1
        cursor -= timedelta(days=1)

    return streak


def _calculate_daily_score_data(target_date: str) -> dict:
    day_data = get_today_habits(target_date)
    score = round((day_data["completed_count"] / day_data["total_count"]) * 100, 2) if day_data["total_count"] else 0.0
    return {
        "date": target_date,
        "score": score,
        "completed_count": day_data["completed_count"],
        "total_count": day_data["total_count"],
        "xp_earned": day_data["earned_xp_today"],
    }


def upsert_daily_score(target_date: str | None = None) -> dict:
    day = target_date or date.today().isoformat()
    score_data = _calculate_daily_score_data(day)
    timestamp = datetime.now().isoformat(timespec="seconds")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO daily_scores (date, score, completed_count, total_count, xp_earned, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                score = excluded.score,
                completed_count = excluded.completed_count,
                total_count = excluded.total_count,
                xp_earned = excluded.xp_earned,
                updated_at = excluded.updated_at
            """,
            (
                score_data["date"],
                score_data["score"],
                score_data["completed_count"],
                score_data["total_count"],
                score_data["xp_earned"],
                timestamp,
            ),
        )
        conn.commit()

    return score_data


def sync_daily_scores() -> None:
    with get_connection() as conn:
        rows = conn.execute("SELECT DISTINCT date FROM habit_logs ORDER BY date ASC").fetchall()
    for row in rows:
        upsert_daily_score(row["date"])


def get_daily_score(target_date: str | None = None) -> dict:
    day = target_date or date.today().isoformat()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT date, score, completed_count, total_count, xp_earned
            FROM daily_scores
            WHERE date = ?
            """,
            (day,),
        ).fetchone()

    if row:
        return dict(row)

    return upsert_daily_score(day)


def refresh_user_stats() -> None:
    total_xp = compute_total_xp()
    level = (total_xp // 100) + 1
    streak = compute_current_streak()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET total_xp = ?, level = ?, current_streak = ?
            WHERE id = (SELECT id FROM users LIMIT 1)
            """,
            (total_xp, level, streak),
        )
        conn.commit()


def get_stats() -> dict:
    refresh_user_stats()
    today_data = get_today_habits()
    today_score = get_daily_score()
    today = date.today()
    week_start = today - timedelta(days=6)

    with get_connection() as conn:
        user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()

        week_rows = conn.execute(
            """
            SELECT hl.date, COALESCE(SUM(h.xp_reward), 0) AS xp
            FROM habit_logs hl
            JOIN habits h ON h.id = hl.habit_id
            WHERE hl.completed = 1
              AND hl.date BETWEEN ? AND ?
            GROUP BY hl.date
            ORDER BY hl.date ASC
            """,
            (week_start.isoformat(), today.isoformat()),
        ).fetchall()

    xp_by_day = {row["date"]: int(row["xp"]) for row in week_rows}
    weekly = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        day_key = day.isoformat()
        weekly.append({"date": day_key, "xp": xp_by_day.get(day_key, 0)})

    current_level = int(user["level"])
    total_xp = int(user["total_xp"])
    xp_into_level = total_xp % 100
    xp_to_next_level = 100 - xp_into_level if xp_into_level != 0 else 0

    return {
        "user": {
            "name": user["name"],
            "total_xp": total_xp,
            "level": current_level,
            "current_streak": int(user["current_streak"]),
            "xp_into_level": xp_into_level,
            "xp_to_next_level": xp_to_next_level,
        },
        "today": {
            "progress_percent": today_data["progress_percent"],
            "earned_xp": today_data["earned_xp_today"],
            "completed_count": today_data["completed_count"],
            "total_count": today_data["total_count"],
            "discipline_score": today_score["score"],
        },
        "weekly_xp": weekly,
    }


def get_history() -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                hl.date,
                COUNT(*) AS completed_count,
                COALESCE(SUM(h.xp_reward), 0) AS xp_earned
            FROM habit_logs hl
            JOIN habits h ON h.id = hl.habit_id
            WHERE hl.completed = 1
            GROUP BY hl.date
            ORDER BY hl.date DESC
            """
        ).fetchall()
        total_habits_row = conn.execute("SELECT COUNT(*) AS count FROM habits").fetchone()
        score_rows = conn.execute(
            """
            SELECT date, score, completed_count, xp_earned
            FROM daily_scores
            """
        ).fetchall()

    total_habits = int(total_habits_row["count"]) if total_habits_row else 0
    max_xp_per_day = sum(seed.xp_reward for seed in HABIT_SEEDS)
    score_map = {row["date"]: dict(row) for row in score_rows}
    days = []
    for row in rows:
        completed_count = int(row["completed_count"])
        percent = round((completed_count / total_habits) * 100, 2) if total_habits else 0.0
        score_value = float(score_map.get(row["date"], {}).get("score", percent))
        days.append(
            {
                "date": row["date"],
                "completed_count": completed_count,
                "total_count": total_habits,
                "completion_percent": percent,
                "xp_earned": int(row["xp_earned"]),
                "discipline_score": score_value,
            }
        )

    activity_map = {day["date"]: day for day in days}
    heatmap_days = []
    cursor = date.today() - timedelta(days=364)
    for _ in range(365):
        key = cursor.isoformat()
        day_data = activity_map.get(
            key,
            {
                "date": key,
                "xp_earned": 0,
                "completed_count": 0,
                "total_count": total_habits,
                "discipline_score": 0.0,
            },
        )
        xp_ratio = (day_data["xp_earned"] / max_xp_per_day) if max_xp_per_day else 0.0
        if day_data["xp_earned"] <= 0:
            intensity = 0
        elif xp_ratio <= 0.25:
            intensity = 1
        elif xp_ratio <= 0.50:
            intensity = 2
        elif xp_ratio <= 0.75:
            intensity = 3
        else:
            intensity = 4

        heatmap_days.append(
            {
                "date": key,
                "xp_earned": day_data["xp_earned"],
                "completed_count": day_data["completed_count"],
                "intensity": intensity,
                "discipline_score": day_data["discipline_score"],
            }
        )
        cursor += timedelta(days=1)

    return {
        "days": days,
        "total_days_tracked": len(days),
        "heatmap": heatmap_days,
    }
