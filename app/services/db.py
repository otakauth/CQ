import json
import sqlite3
from typing import List, Optional, Tuple
from app.domain.models import Question
from app.services.config import DB_PATH

def _get_columns(conn: sqlite3.Connection) -> set:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(questions)")
    cols = {row[1] for row in cur.fetchall()}  # row[1] = column name
    return cols

def _resolve_col(cols: set, preferred: str, fallback: str) -> str:
    return preferred if preferred in cols else fallback

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
            feedbacks=json.loads(r[10]) if len(r) > 10 and r[10] else None
        ))
    return out

def _build_select(cols: set) -> Tuple[str, str, str, str]:
    """
    実DBのカラム名に合わせて SELECT 句を動的生成。
    戻り値は (choices_col, explanations_col, tags_col, feedbacks_col)
    """
    choices_col      = _resolve_col(cols, "choices_json", "choices")
    explanations_col = _resolve_col(cols, "explanations_json", "explanations")
    tags_col         = _resolve_col(cols, "tags_json", "tags")
    feedbacks_col    = _resolve_col(cols, "feedbacks_json", "feedbacks")

    # skill/level/type/prompt/difficulty は両スキーマで同名前提
    select_sql = (
        f"SELECT id,skill,level,type,prompt,"
        f"{choices_col},answer_key,{explanations_col},"
        f"difficulty,{tags_col},{feedbacks_col} FROM questions "
    )
    return select_sql, choices_col, explanations_col, tags_col

def load_questions(skill_filter: Optional[str] = None, limit: int = 5) -> List[Question]:
    with sqlite3.connect(DB_PATH) as conn:
        cols = _get_columns(conn)

        # テーブルが存在しない or 必須列が無い場合は即エラーにしてログで気づけるように
        required_min = {"id", "skill", "level", "type", "prompt", "answer_key", "difficulty"}
        if not required_min.issubset(cols):
            raise sqlite3.OperationalError(
                f"questions テーブルの必須列が不足しています。見つかった列: {sorted(cols)}"
            )

        base_select, *_ = _build_select(cols)

        cur = conn.cursor()
        if skill_filter:
            cur.execute(base_select + "WHERE skill=? ORDER BY RANDOM() LIMIT ?", (skill_filter, limit))
        else:
            cur.execute(base_select + "ORDER BY RANDOM() LIMIT ?", (limit,))
        rows = cur.fetchall()

    return _rows_to_questions(rows)
