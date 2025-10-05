import sqlite3
from pathlib import Path

DB_PATH = Path("data/cq.db")

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
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
            feedbacks_json TEXT   -- ★ 追加
        );
        """)
        # 既存DBに feedbacks_json が無い場合は追加
        cur.execute("PRAGMA table_info(questions)")
        cols = [r[1] for r in cur.fetchall()]
        if "feedbacks_json" not in cols:
            cur.execute("ALTER TABLE questions ADD COLUMN feedbacks_json TEXT")
        conn.commit()

if __name__ == "__main__":
    init_db()
    print("initialized:", DB_PATH)
