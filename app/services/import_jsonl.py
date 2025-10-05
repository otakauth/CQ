import json, sqlite3
from pathlib import Path

DB_PATH = Path("data/cq.db")
SRC = Path("data/questions.jsonl")

def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id TEXT PRIMARY KEY,
        skill TEXT,
        level TEXT,
        type TEXT,
        prompt TEXT,
        choices_json TEXT,
        answer_key TEXT,
        explanations_json TEXT,
        difficulty REAL,
        tags_json TEXT,
        feedbacks_json TEXT
    );
    """)
    cur.execute("PRAGMA table_info(questions)")
    cols = [r[1] for r in cur.fetchall()]
    if "feedbacks_json" not in cols:
        cur.execute("ALTER TABLE questions ADD COLUMN feedbacks_json TEXT")
    conn.commit()

def import_jsonl(src=SRC):
    if not SRC.exists():
        raise FileNotFoundError(SRC)
    with sqlite3.connect(DB_PATH) as conn, SRC.open("r", encoding="utf-8") as f:
        ensure_schema(conn)
        cur = conn.cursor()
        for line in f:
            line = line.strip()
            if not line:
                continue
            q = json.loads(line)
            if q.get("skill") in ("構成", "structure"):
                continue
            cur.execute("""
            INSERT OR REPLACE INTO questions
            (id, skill, level, type, prompt, choices_json, answer_key,
             explanations_json, difficulty, tags_json, feedbacks_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                q["id"],
                q.get("skill"),
                q.get("level"),
                q.get("type"),
                q.get("prompt"),
                json.dumps(q.get("choices"), ensure_ascii=False),
                q.get("answer_key"),
                json.dumps(q.get("explanations"), ensure_ascii=False),
                float(q.get("difficulty", 0.5)),
                json.dumps(q.get("tags"), ensure_ascii=False),
                json.dumps(q.get("feedbacks"), ensure_ascii=False),   # ★ 追加
            ))
        conn.commit()

if __name__ == "__main__":
    import_jsonl()
    print("imported into:", DB_PATH)
