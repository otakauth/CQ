# app/services/db.py
import json
import sqlite3
from typing import List, Optional, Set
from app.domain.models import Question
from app.services.config import DB_PATH

# ---- 内部ヘルパ ----

def _get_columns(conn: sqlite3.Connection) -> Set[str]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='questions'")
    if not cur.fetchone():
        return set()
    cur.execute("PRAGMA table_info(questions)")
    return {row[1] for row in cur.fetchall()}  # row[1] = column name

def _col(cols: Set[str], name: str, default_sql: str) -> str:
    """
    実DBに 'name' 列があればそのまま、無ければ default_sql を使って
    SELECT句で同名エイリアスにする（例: \"'' AS level\" や \"0.5 AS difficulty\"）
    """
    return name if name in cols else f"{default_sql} AS {name}"

def _json_col(cols: Set[str], preferred: str, fallback: str) -> str:
    """
    JSON系の列は *_json 優先、無ければ旧名、どちらも無ければ NULL を返す。
    戻り値は SELECT句にそのまま置けるSQL断片。
    """
    if preferred in cols:
        return preferred
    if fallback in cols:
        return fallback
    return f"NULL AS {preferred}"

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

def _build_select(cols: Set[str]) -> str:
    """
    実DBの列に合わせて安全な SELECT を構築。
    無い列はリテラルで補完し、最終的に以下の順で返す：
      id, skill, level, type, prompt,
      choices_json, answer_key, explanations_json, difficulty, tags_json, feedbacks_json
    """
    # 基本列（無ければ既定値で補完）
    id_expr         = _col(cols, "id",         "''")
    skill_expr      = _col(cols, "skill",      "''")
    level_expr      = _col(cols, "level",      "''")
    type_expr       = _col(cols, "type",       "''")
    prompt_expr     = _col(cols, "prompt",     "''")
    answer_key_expr = _col(cols, "answer_key", "NULL")
    difficulty_expr = _col(cols, "difficulty", "0.5")

    # JSON系（*_json 優先→旧名→NULL）
    choices_expr      = _json_col(cols, "choices_json",      "choices")
    explanations_expr = _json_col(cols, "explanations_json", "explanations")
    tags_expr         = _json_col(cols, "tags_json",         "tags")
    feedbacks_expr    = _json_col(cols, "feedbacks_json",    "feedbacks")

    select_sql = (
        "SELECT "
        f"{id_expr}, {skill_expr}, {level_expr}, {type_expr}, {prompt_expr}, "
        f"{choices_expr}, {answer_key_expr}, {explanations_expr}, "
        f"{difficulty_expr}, {tags_expr}, {feedbacks_expr} "
        "FROM questions "
        "ORDER BY RANDOM() "
        "LIMIT ?"
    )
    return select_sql

# ---- 公開API ----

def load_questions(skill_filter: Optional[str] = None, limit: int = 5) -> List[Question]:
    with sqlite3.connect(DB_PATH) as conn:
        cols = _get_columns(conn)
        cur = conn.cursor()

        # テーブルが無い場合は空配列（UI側で「不足」警告を出す前提）
        if not cols:
            return []

        # SELECT句を構築（WHERE句はここで組み立てる）
        select_sql = _build_select(cols)
        # "ORDER BY RANDOM() LIMIT ?" の部分を除去してベース化
        base_sql = select_sql.replace("ORDER BY RANDOM() LIMIT ?", "")

        params = []
        if skill_filter and "skill" in cols:
            base_sql += " WHERE skill=?"
            params.append(skill_filter)

        base_sql += " ORDER BY RANDOM() LIMIT ?"
        params.append(limit)

        cur.execute(base_sql, params)
        rows = cur.fetchall()

    return _rows_to_questions(rows)
