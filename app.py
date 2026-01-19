import sqlite3
from datetime import date, datetime, timedelta
import secrets
from pathlib import Path
from typing import Dict, List, Tuple

from flask import (
    Flask,
    jsonify,
    request,
    send_from_directory,
    session,
)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "luleme.db"

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
app.config.update(
    SECRET_KEY="replace-this-with-a-random-secret",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ============ Battle (in-memory, 60s) ============
BATTLE_ROOMS = {}
BATTLE_DURATION = 60  # seconds


def _gen_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _now():
    return datetime.utcnow()


def _room_state(room: dict) -> dict:
    started_at = room.get("started_at")
    finished_at = room.get("finished_at")
    remaining = BATTLE_DURATION
    started = False
    if started_at:
        started = True
        delta = (_now() - started_at).total_seconds()
        remaining = max(0, BATTLE_DURATION - int(delta))
        if remaining == 0 and not finished_at:
            room["finished_at"] = _now()
    players = sorted(
        room.get("players", {}).values(),
        key=lambda x: x.get("count", 0),
        reverse=True,
    )
    return {
        "code": room["code"],
        "creator_id": room["creator_id"],
        "creator_name": room["creator_name"],
        "players": players,
        "started": started,
        "remaining": remaining,
        "finished": bool(room.get("finished_at")),
        "surrendered": room.get("surrendered", []),
        "surrender_result": room.get("surrender_result"),
        "winner_id": room.get("winner_id"),
    }


def _cleanup_rooms():
    """Remove finished rooms after a grace period to avoid leaks."""
    to_delete = []
    for code, room in BATTLE_ROOMS.items():
        finished_at = room.get("finished_at")
        created_at = room.get("created_at")
        # expire if finished 5 minutes ago or older than 30 minutes
        if finished_at and (_now() - finished_at).total_seconds() > 300:
            to_delete.append(code)
        elif not finished_at and (_now() - created_at).total_seconds() > 1800:
            to_delete.append(code)
    for code in to_delete:
        BATTLE_ROOMS.pop(code, None)


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, date),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )


def error(message: str, status: int = 400):
    return jsonify({"message": message}), status


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return user


def require_login():
    user = current_user()
    if not user:
        return None, error("未登录，请先登录", 401)
    return user, None


def fetch_all_records(user_id: int) -> Dict[str, int]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date, count FROM records WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {row["date"]: row["count"] for row in rows}


def compute_streak(records: Dict[str, int]) -> int:
    streak = 0
    cursor = date.today()
    while records.get(cursor.isoformat(), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def compute_last7(records: Dict[str, int]) -> int:
    total = 0
    cursor = date.today()
    for _ in range(7):
        total += records.get(cursor.isoformat(), 0)
        cursor -= timedelta(days=1)
    return total


def compute_achievements(total: int, max_day: int, streak: int, last7: int) -> List[dict]:
    return [
        {
            "id": "first_blood",
            "name": "初次冲锋",
            "desc": "第一次动手，万事开头难",
            "target": 1,
            "progress": min(total, 1),
            "unlocked": total >= 1,
        },
        {
            "id": "warm_up",
            "name": "热身运动",
            "desc": "累计 5 次，小撸怡情",
            "target": 5,
            "progress": min(total, 5),
            "unlocked": total >= 5,
        },
        {
            "id": "iron_hand",
            "name": "铁手少年",
            "desc": "累计 20 次，手感渐入佳境",
            "target": 20,
            "progress": min(total, 20),
            "unlocked": total >= 20,
        },
        {
            "id": "thunder_finger",
            "name": "霹雳手指",
            "desc": "累计 50 次，手速如风",
            "target": 50,
            "progress": min(total, 50),
            "unlocked": total >= 50,
        },
        {
            "id": "thousand_hand",
            "name": "千手观音",
            "desc": "累计 100 次，众生平等",
            "target": 100,
            "progress": min(total, 100),
            "unlocked": total >= 100,
        },
        {
            "id": "combo_2",
            "name": "双杀达人",
            "desc": "单日达到 2 次，手还暖着呢",
            "target": 2,
            "progress": min(max_day, 2),
            "unlocked": max_day >= 2,
        },
        {
            "id": "combo_3",
            "name": "三连击",
            "desc": "单日达到 3 次，猛男本男",
            "target": 3,
            "progress": min(max_day, 3),
            "unlocked": max_day >= 3,
        },
        {
            "id": "combo_5",
            "name": "五连鞭",
            "desc": "单日达到 5 次，注意补水",
            "target": 5,
            "progress": min(max_day, 5),
            "unlocked": max_day >= 5,
        },
        {
            "id": "combo_10",
            "name": "爆肝铁人",
            "desc": "单日达到 10 次，手速超神",
            "target": 10,
            "progress": min(max_day, 10),
            "unlocked": max_day >= 10,
        },
        {
            "id": "combo_20",
            "name": "人体打桩机",
            "desc": "单日达到 20 次，求你歇歇",
            "target": 20,
            "progress": min(max_day, 20),
            "unlocked": max_day >= 20,
        },
        {
            "id": "weekly_warrior",
            "name": "周末狂欢",
            "desc": "7 天内累计 7 次，周末不能闲",
            "target": 7,
            "progress": min(last7, 7),
            "unlocked": last7 >= 7,
        },
        {
            "id": "weekly_overtime",
            "name": "周末加班王",
            "desc": "近 7 天累计 14 次，手比班还勤",
            "target": 14,
            "progress": min(last7, 14),
            "unlocked": last7 >= 14,
        },
        {
            "id": "weekly_machine",
            "name": "周更机器",
            "desc": "近 7 天累计 21 次，怀疑你是 AI",
            "target": 21,
            "progress": min(last7, 21),
            "unlocked": last7 >= 21,
        },
        {
            "id": "streak_3",
            "name": "三天不洗手",
            "desc": "连续 3 天都撸，味道上头",
            "target": 3,
            "progress": min(streak, 3),
            "unlocked": streak >= 3,
        },
        {
            "id": "streak_7",
            "name": "一周不歇",
            "desc": "连续 7 天都撸，手腕小马达",
            "target": 7,
            "progress": min(streak, 7),
            "unlocked": streak >= 7,
        },
        {
            "id": "streak_14",
            "name": "半月狂魔",
            "desc": "连续 14 天，邻居都认识你",
            "target": 14,
            "progress": min(streak, 14),
            "unlocked": streak >= 14,
        },
        {
            "id": "streak_30",
            "name": "月度劳模",
            "desc": "连续 30 天，手劲持久",
            "target": 30,
            "progress": min(streak, 30),
            "unlocked": streak >= 30,
        },
        {
            "id": "total_200",
            "name": "手速王者",
            "desc": "总次数达到 200，传说中的单挑王",
            "target": 200,
            "progress": min(total, 200),
            "unlocked": total >= 200,
        },
        {
            "id": "total_365",
            "name": "人造日历",
            "desc": "总次数达到 365，比日历还准时",
            "target": 365,
            "progress": min(total, 365),
            "unlocked": total >= 365,
        },
    ]


def get_month_range(year: int, month: int) -> Tuple[str, str]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def get_month_records(user_id: int, year: int, month: int) -> Dict[str, int]:
    start, end = get_month_range(year, month)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date, count FROM records WHERE user_id = ? AND date >= ? AND date < ?",
            (user_id, start, end),
        ).fetchall()
    return {row["date"]: row["count"] for row in rows}


def build_summary(user_id: int) -> Tuple[dict, dict]:
    today = date.today()
    today_str = today.isoformat()
    month_prefix = today.strftime("%Y-%m")

    all_records = fetch_all_records(user_id)
    total_count = sum(all_records.values())
    today_count = all_records.get(today_str, 0)
    month_count = sum(
        count for dt, count in all_records.items() if dt.startswith(month_prefix)
    )
    max_day = max(all_records.values() or [0])
    streak = compute_streak(all_records)
    last7 = compute_last7(all_records)

    achievements = compute_achievements(total_count, max_day, streak, last7)
    current_month_records = get_month_records(user_id, today.year, today.month)

    summary = {
        "today": today_str,
        "today_count": today_count,
        "month_count": month_count,
        "total_count": total_count,
        "current_streak": streak,
        "last7_count": last7,
        "max_day_count": max_day,
        "current_year": today.year,
        "current_month": today.month,
        "achievements": achievements,
    }
    return summary, current_month_records


@app.route("/")
def root():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if len(username) < 3:
        return error("用户名至少 3 个字符")
    if len(password) < 6:
        return error("密码至少 6 位")

    now = datetime.utcnow().isoformat()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), now),
            )
    except sqlite3.IntegrityError:
        return error("用户名已存在，请换一个")

    user = (
        get_db()
        .execute(
            "SELECT id, username, created_at FROM users WHERE username = ?", (username,)
        )
        .fetchone()
    )
    session["user_id"] = user["id"]
    return jsonify({"message": "注册成功", "user": {"username": user["username"]}})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    with get_db() as conn:
        user = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return error("用户名或密码错误", 401)

    session["user_id"] = user["id"]
    return jsonify({"message": "登录成功", "user": {"username": user["username"]}})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return jsonify({"message": "已退出"})


@app.route("/api/me")
def me():
    user, err = require_login()
    if err:
        return err
    summary, records = build_summary(user["id"])
    return jsonify(
        {
            "user": {"id": user["id"], "username": user["username"]},
            "summary": summary,
            "records": records,
        }
    )


@app.route("/api/records")
def records():
    user, err = require_login()
    if err:
        return err

    try:
        year = int(request.args.get("year"))
        month = int(request.args.get("month"))
        if not (1 <= month <= 12):
            raise ValueError
    except (TypeError, ValueError):
        return error("year 或 month 参数不合法")

    records = get_month_records(user["id"], year, month)
    return jsonify({"records": records})


@app.route("/api/record", methods=["POST"])
def record_today():
    user, err = require_login()
    if err:
        return err

    today = date.today().isoformat()
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO records (user_id, date, count, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(user_id, date)
            DO UPDATE SET count = count + 1, updated_at = excluded.updated_at
            """,
            (user["id"], today, now, now),
        )

    summary, records = build_summary(user["id"])
    return jsonify(
        {
            "message": "记录成功",
            "summary": summary,
            "records": records,
        }
    )


@app.route("/api/record/today", methods=["DELETE"])
def clear_today():
    user, err = require_login()
    if err:
        return err
    today = date.today().isoformat()
    with get_db() as conn:
        conn.execute(
            "DELETE FROM records WHERE user_id = ? AND date = ?",
            (user["id"], today),
        )
    summary, records = build_summary(user["id"])
    return jsonify(
        {
            "message": "已清除今日记录",
            "summary": summary,
            "records": records,
        }
    )


@app.route("/api/battle/create", methods=["POST"])
def battle_create():
    user, err = require_login()
    if err:
        return err
    _cleanup_rooms()
    code = _gen_code()
    BATTLE_ROOMS[code] = {
        "code": code,
        "creator_id": user["id"],
        "creator_name": user["username"],
        "players": {
            user["id"]: {"user_id": user["id"], "username": user["username"], "count": 0, "ready": False}
        },
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
    }
    return jsonify({"message": "已创建房间", "code": code, "state": _room_state(BATTLE_ROOMS[code])})


@app.route("/api/battle/join", methods=["POST"])
def battle_join():
    user, err = require_login()
    if err:
        return err
    data = request.get_json() or {}
    code = (data.get("code") or "").upper()
    room = BATTLE_ROOMS.get(code)
    if not room:
        return error("房间不存在或已过期", 404)
    if room.get("finished_at"):
        return error("房间已结束", 400)
    players = room.setdefault("players", {})
    players[user["id"]] = {
        "user_id": user["id"], 
        "username": user["username"], 
        "count": 0,
        "ready": False
    }
    return jsonify({"message": "已加入", "state": _room_state(room)})


@app.route("/api/battle/ready", methods=["POST"])
def battle_ready():
    user, err = require_login()
    if err:
        return err
    data = request.get_json() or {}
    code = (data.get("code") or "").upper()
    ready = data.get("ready", False)
    room = BATTLE_ROOMS.get(code)
    if not room:
        return error("房间不存在或已过期", 404)
    if room.get("finished_at"):
        return error("房间已结束", 400)
    if room.get("started_at"):
        return error("对战已开始", 400)
    players = room.setdefault("players", {})
    if user["id"] not in players:
        return error("你不在该房间中", 400)
    players[user["id"]]["ready"] = ready
    return jsonify({"message": "准备状态已更新", "state": _room_state(room)})


@app.route("/api/battle/leave", methods=["POST"])
def battle_leave():
    user, err = require_login()
    if err:
        return err
    data = request.get_json() or {}
    code = (data.get("code") or "").upper()
    room = BATTLE_ROOMS.get(code)
    if not room:
        return error("房间不存在或已过期", 404)
    players = room.setdefault("players", {})
    if user["id"] not in players:
        return error("你不在该房间中", 400)
    
    is_creator = room["creator_id"] == user["id"]
    del players[user["id"]]
    
    # 如果房间还有其他玩家且当前用户是房主，转让房主
    if len(players) > 0 and is_creator:
        # 选择第一个加入的玩家作为新房主
        new_creator_id = list(players.keys())[0]
        new_creator = players[new_creator_id]
        room["creator_id"] = new_creator_id
        room["creator_name"] = new_creator["username"]
        return jsonify({"message": "已离开房间，房主已转让", "state": _room_state(room), "new_creator": True})
    
    # 如果房间没有其他玩家，删除房间
    if len(players) == 0:
        del BATTLE_ROOMS[code]
        return jsonify({"message": "房间已解散", "room_deleted": True})
    
    return jsonify({"message": "已离开房间", "state": _room_state(room)})


@app.route("/api/battle/start", methods=["POST"])
def battle_start():
    user, err = require_login()
    if err:
        return err
    data = request.get_json() or {}
    code = (data.get("code") or "").upper()
    room = BATTLE_ROOMS.get(code)
    if not room:
        return error("房间不存在或已过期", 404)
    if room["creator_id"] != user["id"]:
        return error("只有房主能开始", 403)
    if room.get("finished_at"):
        return error("房间已结束", 400)
    if room.get("started_at"):
        return jsonify({"message": "已开始", "state": _room_state(room)})
    players = room.get("players", {})
    if len(players) < 2:
        return error("至少 2 人才能开始", 400)
    # 开始对战，设置所有玩家的状态
    room["started_at"] = _now()
    room["finished_at"] = None
    return jsonify({"message": "对战开始！", "state": _room_state(room)})


@app.route("/api/battle/tap", methods=["POST"])
def battle_tap():
    user, err = require_login()
    if err:
        return err
    data = request.get_json() or {}
    code = (data.get("code") or "").upper()
    room = BATTLE_ROOMS.get(code)
    if not room:
        return error("房间不存在或已过期", 404)
    state = _room_state(room)
    if not state["started"]:
        return error("对战未开始", 400)
    if state["finished"] or state["remaining"] <= 0:
        room["finished_at"] = _now()
        return error("已结束", 400)
    players = room.setdefault("players", {})
    if user["id"] not in players:
        players[user["id"]] = {"user_id": user["id"], "username": user["username"], "count": 0}
    players[user["id"]]["count"] += 1
    return jsonify({"message": "已记录", "state": _room_state(room)})


@app.route("/api/battle/state")
def battle_state():
    user, err = require_login()
    if err:
        return err
    code = (request.args.get("code") or "").upper()
    room = BATTLE_ROOMS.get(code)
    if not room:
        return error("房间不存在或已过期", 404)
    return jsonify({"state": _room_state(room)})


@app.route("/api/battle/surrender", methods=["POST"])
def battle_surrender():
    user, err = require_login()
    if err:
        return err
    data = request.get_json() or {}
    code = (data.get("code") or "").upper()
    room = BATTLE_ROOMS.get(code)
    if not room:
        return error("房间不存在或已过期", 404)
    
    state = _room_state(room)
    if not state["started"]:
        return error("对战未开始", 400)
    if state["finished"]:
        return error("对战已结束", 400)
    
    # 检查用户是否在房间中（state["players"]是数组，需要查找user_id）
    player_in_room = any(p["user_id"] == user["id"] for p in state["players"])
    if not player_in_room:
        return error("你不在房间中", 400)
    
    # 记录投降者
    room.setdefault("surrendered", [])
    if user["id"] not in room["surrendered"]:
        room["surrendered"].append(user["id"])
    
    # 检查是否所有玩家都投降了（平局）
    players = room.get("players", {})
    if len(room["surrendered"]) >= len(players):
        room["finished_at"] = _now()
        room["surrender_result"] = "draw"
        return jsonify({"message": "所有玩家都已投降，平局！", "state": _room_state(room)})
    
    # 找到未投降的玩家作为获胜者
    winner_id = None
    for player_id in players:
        if player_id not in room["surrendered"]:
            winner_id = player_id
            break
    
    if winner_id:
        room["finished_at"] = _now()
        room["surrender_result"] = "surrender"
        room["winner_id"] = winner_id
        return jsonify({"message": "已投降", "state": _room_state(room)})
    
    return jsonify({"message": "已记录", "state": _room_state(room)})


@app.route("/api/battle/rooms")
def battle_rooms():
    user, err = require_login()
    if err:
        return err
    _cleanup_rooms()
    # 返回所有未开始的房间
    available_rooms = []
    for room in BATTLE_ROOMS.values():
        if not room.get("started_at") and not room.get("finished_at"):
            state = _room_state(room)
            available_rooms.append({
                "code": state["code"],
                "creator_name": state["creator_name"],
                "player_count": len(state["players"]),
                "created_at": room["created_at"].isoformat()
            })
    # 按创建时间倒序排列
    available_rooms.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify({"rooms": available_rooms})


@app.route("/api/password/change", methods=["POST"])
def password_change():
    user, err = require_login()
    if err:
        return err
    data = request.get_json() or {}
    old_password = data.get("old_password") or ""
    new_password = data.get("new_password") or ""
    if len(new_password) < 6:
        return error("新密码至少 6 位")
    with get_db() as conn:
        db_user = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
        if not db_user or not check_password_hash(db_user["password_hash"], old_password):
            return error("原密码不正确", 400)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user["id"]),
        )
    return jsonify({"message": "密码已修改"})


@app.route("/api/password/reset", methods=["POST"])
def password_reset():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    new_password = data.get("new_password") or ""
    if len(username) < 3:
        return error("用户名无效")
    if len(new_password) < 6:
        return error("新密码至少 6 位")
    with get_db() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not user:
            return error("用户不存在", 404)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user["id"]),
        )
    return jsonify({"message": "密码已重置，请用新密码登录"})


def leaderboard_query(query: str, params: Tuple = ()) -> List[dict]:
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {"username": row["username"], "total": row["total"] or 0, "rank": idx + 1}
        for idx, row in enumerate(rows)
    ]


@app.route("/api/leaderboard")
def leaderboard():
    today = date.today()
    month_key = today.strftime("%Y-%m")

    total_board = leaderboard_query(
        """
        SELECT u.username, COALESCE(SUM(r.count), 0) AS total
        FROM users u
        LEFT JOIN records r ON r.user_id = u.id
        GROUP BY u.id
        ORDER BY total DESC, u.created_at ASC
        LIMIT 10
        """
    )

    month_board = leaderboard_query(
        """
        SELECT u.username, COALESCE(SUM(r.count), 0) AS total
        FROM users u
        LEFT JOIN records r ON r.user_id = u.id AND substr(r.date, 1, 7) = ?
        GROUP BY u.id
        ORDER BY total DESC, u.created_at ASC
        LIMIT 10
        """,
        (month_key,),
    )

    return jsonify({"total": total_board, "month": month_board, "month_key": month_key})


@app.errorhandler(404)
def not_found(_):
    return error("未找到资源", 404)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
