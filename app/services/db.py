import json, sqlite3
from pathlib import Path
from typing import List, Optional
from app.domain.models import Question

DB_PATH = Path("data/cq.db")

def _rows_to_questions(rows) -> List[Question]:
    out: List[Question] = []
    for r in rows:
        out.append(Question(
            id=r[0],
            skill=r[1],
            level=r[2],
            type=r[3],
            prompt=r[4],
            choices=json.loads(r[5]) if r[5] else [],
            answer_key=r[6],
            explanations=json.loads(r[7]) if r[7] else {},
            difficulty=r[8] if r[8] is not None else 0.5,
            tags=json.loads(r[9]) if r[9] else [],
            feedbacks=json.loads(r[10]) if len(r) > 10 and r[10] else None  # ★ 追加
        ))
    return out

def load_questions(skill_filter: Optional[str] = None, limit: int = 5) -> List[Question]:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        base = ("SELECT id,skill,level,type,prompt,choices_json,answer_key,"
                "explanations_json,difficulty,tags_json,feedbacks_json FROM questions ")
        if skill_filter:
            cur.execute(base + "WHERE skill=? ORDER BY RANDOM() LIMIT ?", (skill_filter, limit))
        else:
            cur.execute(base + "ORDER BY RANDOM() LIMIT ?", (limit,))
        rows = cur.fetchall()
    return _rows_to_questions(rows)
