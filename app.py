from flask import Flask, render_template, request, jsonify, make_response
import sqlite3
import time
import secrets
import threading
import os

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "stats.db")
LOCK = threading.Lock()

# Online tracking (RAM): aktyvūs per paskutines 30s
LAST_SEEN = {}  # sid -> last_seen_ts
ONLINE_WINDOW_SEC = 30

_INIT_DONE = False


def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def db_init():
    with LOCK:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS counters (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            )
        """)
        cur.execute("INSERT OR IGNORE INTO counters (key, value) VALUES ('total_views', 0)")
        conn.commit()
        conn.close()


def ensure_init():
    global _INIT_DONE
    if _INIT_DONE:
        return
    db_init()
    _INIT_DONE = True


def get_total_views() -> int:
    ensure_init()
    with LOCK:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("SELECT value FROM counters WHERE key='total_views'")
        row = cur.fetchone()
        conn.close()
        return int(row[0]) if row else 0


def inc_total_views():
    ensure_init()
    with LOCK:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("UPDATE counters SET value = value + 1 WHERE key='total_views'")
        conn.commit()
        conn.close()


def get_sid() -> str:
    sid = request.cookies.get("sid")
    if not sid or len(sid) < 16:
        sid = secrets.token_urlsafe(16)
    return sid


def mark_seen(sid: str):
    now = int(time.time())
    LAST_SEEN[sid] = now
    cutoff = now - ONLINE_WINDOW_SEC
    for k, ts in list(LAST_SEEN.items()):
        if ts < cutoff:
            LAST_SEEN.pop(k, None)


@app.get("/")
def home():
    sid = get_sid()
    inc_total_views()
    mark_seen(sid)

    resp = make_response(render_template("index.html"))
    resp.set_cookie("sid", sid, max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax")
    return resp


@app.post("/ping")
def ping():
    sid = get_sid()
    mark_seen(sid)

    resp = jsonify({"ok": True})
    resp.set_cookie("sid", sid, max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax")
    return resp


@app.get("/stats")
def stats():
    sid = get_sid()
    mark_seen(sid)

    now = int(time.time())
    cutoff = now - ONLINE_WINDOW_SEC
    online = sum(1 for ts in LAST_SEEN.values() if ts >= cutoff)

    total = get_total_views()
    resp = jsonify({"online": online, "total_views": total})
    resp.set_cookie("sid", sid, max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax")
    return resp


if __name__ == "__main__":
    app.run(debug=True)
