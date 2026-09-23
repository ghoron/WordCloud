"""Live Wordcloud - deelnemers sturen woorden in via hun telefoon,
de presentator toont een live wolk op het grote scherm."""
import csv
import io
import os
import re
import secrets
import sqlite3
from functools import wraps

import qrcode
import qrcode.image.svg
from flask import (Flask, Response, g, jsonify, redirect, render_template,
                   request, session, url_for)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "verander-mij-" + secrets.token_hex(8))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "wordcloud")
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DATA_DIR, "wordcloud.db")
MAX_WORD_LEN = 40


# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            participant TEXT NOT NULL,
            word TEXT NOT NULL,
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_entries_q ON entries(question_id);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    """)
    for k, v in (("current_question", ""), ("is_open", "1"), ("max_words", "3")):
        conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


def get_setting(key):
    row = db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key, value):
    db().execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))
    db().commit()


def current_question():
    qid = get_setting("current_question")
    if not qid:
        return None
    return db().execute("SELECT id, text FROM questions WHERE id=?", (qid,)).fetchone()


def normalize(word):
    word = re.sub(r"\s+", " ", (word or "").strip().lower())
    word = word.strip(".,;:!?\"'()[]{}")
    return word[:MAX_WORD_LEN]


def participant_id():
    return request.cookies.get("pid") or ""


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            if request.path.startswith("/api/"):
                return jsonify(error="niet ingelogd"), 401
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper


# ---------- deelnemers ----------
@app.route("/")
def join():
    resp = app.make_response(render_template("join.html"))
    if not request.cookies.get("pid"):
        resp.set_cookie("pid", secrets.token_hex(12), max_age=60 * 60 * 24 * 30,
                        samesite="Lax")
    return resp


@app.route("/api/state")
def state():
    q = current_question()
    pid = participant_id()
    mine = []
    if q and pid:
        mine = [r["word"] for r in db().execute(
            "SELECT word FROM entries WHERE question_id=? AND participant=? ORDER BY id",
            (q["id"], pid))]
    return jsonify(
        question={"id": q["id"], "text": q["text"]} if q else None,
        open=get_setting("is_open") == "1",
        max_words=int(get_setting("max_words") or 3),
        mine=mine,
    )


@app.route("/api/submit", methods=["POST"])
def submit():
    pid = participant_id()
    q = current_question()
    if not pid:
        return jsonify(error="Herlaad de pagina en probeer opnieuw."), 400
    if not q:
        return jsonify(error="Er staat nog geen vraag klaar."), 400
    if get_setting("is_open") != "1":
        return jsonify(error="Insturen is gesloten voor deze vraag."), 400
    data = request.get_json(silent=True) or {}
    if int(data.get("question_id") or 0) != q["id"]:
        return jsonify(error="De vraag is net gewisseld. Kijk even naar de nieuwe vraag."), 409
    word = normalize(data.get("word"))
    if not word:
        return jsonify(error="Typ eerst een woord."), 400
    max_words = int(get_setting("max_words") or 3)
    used = db().execute("SELECT COUNT(*) c FROM entries WHERE question_id=? AND participant=?",
                        (q["id"], pid)).fetchone()["c"]
    if used >= max_words:
        return jsonify(error=f"Je hebt al {max_words} woorden ingestuurd."), 400
    dup = db().execute("SELECT 1 FROM entries WHERE question_id=? AND participant=? AND word=?",
                       (q["id"], pid, word)).fetchone()
    if dup:
        return jsonify(error="Dat woord heb je al ingestuurd."), 400
    db().execute("INSERT INTO entries (question_id, participant, word) VALUES (?,?,?)",
                 (q["id"], pid, word))
    db().commit()
    return jsonify(ok=True)


# ---------- presentator ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("presenter"))
        error = "Dat wachtwoord klopt niet."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/presenter")
@admin_required
def presenter():
    return render_template("presenter.html", join_url=request.host_url.rstrip("/"))


@app.route("/qr.svg")
def qr_svg():
    img = qrcode.make(request.host_url, image_factory=qrcode.image.svg.SvgPathImage,
                      box_size=10, border=1)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), mimetype="image/svg+xml")


@app.route("/api/admin/overview")
@admin_required
def overview():
    q = current_question()
    qs = [dict(r) for r in db().execute("""
        SELECT q.id, q.text, q.position, COUNT(e.id) AS entries,
               COUNT(DISTINCT e.participant) AS participants
        FROM questions q LEFT JOIN entries e ON e.question_id = q.id
        GROUP BY q.id ORDER BY q.position, q.id""")]
    words, participants = [], 0
    if q:
        words = [dict(r) for r in db().execute("""
            SELECT word, COUNT(*) AS count FROM entries WHERE question_id=?
            GROUP BY word ORDER BY count DESC, word""", (q["id"],))]
        participants = db().execute(
            "SELECT COUNT(DISTINCT participant) c FROM entries WHERE question_id=?",
            (q["id"],)).fetchone()["c"]
    return jsonify(
        current=q["id"] if q else None,
        question=q["text"] if q else None,
        open=get_setting("is_open") == "1",
        max_words=int(get_setting("max_words") or 3),
        questions=qs, words=words, participants=participants,
    )


@app.route("/api/admin/questions", methods=["POST"])
@admin_required
def add_question():
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()[:200]
    if not text:
        return jsonify(error="Vul een vraag in."), 400
    pos = db().execute("SELECT COALESCE(MAX(position), 0) + 1 p FROM questions").fetchone()["p"]
    cur = db().execute("INSERT INTO questions (text, position) VALUES (?, ?)", (text, pos))
    db().commit()
    if not get_setting("current_question"):
        set_setting("current_question", cur.lastrowid)
    return jsonify(ok=True)


@app.route("/api/admin/questions/<int:qid>", methods=["DELETE"])
@admin_required
def delete_question(qid):
    db().execute("DELETE FROM entries WHERE question_id=?", (qid,))
    db().execute("DELETE FROM questions WHERE id=?", (qid,))
    db().commit()
    if get_setting("current_question") == str(qid):
        first = db().execute("SELECT id FROM questions ORDER BY position, id LIMIT 1").fetchone()
        set_setting("current_question", first["id"] if first else "")
    return jsonify(ok=True)


@app.route("/api/admin/current", methods=["POST"])
@admin_required
def set_current():
    qid = (request.get_json(silent=True) or {}).get("id")
    if not db().execute("SELECT 1 FROM questions WHERE id=?", (qid,)).fetchone():
        return jsonify(error="Onbekende vraag."), 404
    set_setting("current_question", qid)
    set_setting("is_open", "1")
    return jsonify(ok=True)


@app.route("/api/admin/settings", methods=["POST"])
@admin_required
def update_settings():
    data = request.get_json(silent=True) or {}
    if "open" in data:
        set_setting("is_open", "1" if data["open"] else "0")
    if "max_words" in data:
        set_setting("max_words", max(1, min(10, int(data["max_words"]))))
    return jsonify(ok=True)


@app.route("/api/admin/remove_word", methods=["POST"])
@admin_required
def remove_word():
    data = request.get_json(silent=True) or {}
    db().execute("DELETE FROM entries WHERE question_id=? AND word=?",
                 (data.get("question_id"), data.get("word")))
    db().commit()
    return jsonify(ok=True)


@app.route("/api/admin/clear", methods=["POST"])
@admin_required
def clear_question():
    qid = (request.get_json(silent=True) or {}).get("question_id")
    db().execute("DELETE FROM entries WHERE question_id=?", (qid,))
    db().commit()
    return jsonify(ok=True)


@app.route("/export.csv")
@admin_required
def export_csv():
    rows = db().execute("""
        SELECT q.text AS vraag, e.word AS woord, COUNT(*) AS aantal
        FROM entries e JOIN questions q ON q.id = e.question_id
        GROUP BY q.id, e.word ORDER BY q.position, aantal DESC, e.word""")
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["vraag", "woord", "aantal"])
    for r in rows:
        writer.writerow([r["vraag"], r["woord"], r["aantal"]])
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=wordcloud.csv"})


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
