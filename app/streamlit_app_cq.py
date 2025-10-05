# -*- coding: utf-8 -*-

# -------------------------------
# 起動前セットアップ：DBが無ければJSONLから自動生成
# -------------------------------
from pathlib import Path
import os

# import_jsonl は両対応（app.services / services）
try:
    from app.services import import_jsonl as _imp
except Exception:
    from services import import_jsonl as _imp  # 旧構成向け

# DB/JSONL パスも両対応
try:
    from app.services.config import DB_PATH, JSONL_PATH
except Exception:
    DB_PATH = Path("data/cq.db")
    JSONL_PATH = Path("data/questions.jsonl")

# -*- coding: utf-8 -*-

# -------------------------------
# 起動前セットアップ：DBが無ければJSONLから自動生成＋スキーマ検証
# -------------------------------
from pathlib import Path
import os
import sqlite3

# import_jsonl は両対応（app.services / services）
try:
    from app.services import import_jsonl as _imp
except Exception:
    from services import import_jsonl as _imp  # 旧構成向け

# DB/JSONL パスも両対応
try:
    from app.services.config import DB_PATH, JSONL_PATH
except Exception:
    DB_PATH = Path("data/cq.db")
    JSONL_PATH = Path("data/questions.jsonl")

REQUIRED_MIN_COLS = {"id", "skill", "level", "type", "prompt", "answer_key", "difficulty"}

def _current_cols(db_path: Path) -> set:
    if not db_path.exists():
        return set()
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='questions'")
            if not cur.fetchone():
                return set()
            cur.execute("PRAGMA table_info(questions)")
            return {row[1] for row in cur.fetchall()}  # row[1] = column name
    except Exception:
        return set()

def _schema_is_valid(db_path: Path) -> bool:
    cols = _current_cols(db_path)
    return bool(cols) and REQUIRED_MIN_COLS.issubset(cols)

def _run_import(jsonl: Path, db: Path):
    # import_jsonl の関数名が run / import_jsonl どちらでも動くように
    if hasattr(_imp, "run"):
        _imp.run(str(jsonl), str(db))
    elif hasattr(_imp, "import_jsonl"):
        _imp.import_jsonl()
    else:
        raise RuntimeError("import_jsonl.py に run() も import_jsonl() も見つかりません。")

def _ensure_db():
    """DB が無い / 壊れている / スキーマが古い ときに JSONL→DB を実行"""
    jsonl = Path(JSONL_PATH)
    db = Path(DB_PATH)

    need = False

    # 1) 物理的に無い/小さすぎる → 作成
    if (not db.exists()) or (db.stat().st_size < 1024):
        need = True

    # 2) スキーマ検証（必須列が無ければ再作成）
    if not need and not _schema_is_valid(db):
        need = True

    # 3) JSONL の方が新しければ再作成
    if not need:
        try:
            if jsonl.exists() and jsonl.stat().st_mtime > db.stat().st_mtime:
                need = True
        except Exception:
            need = True

    # 4) 環境変数で強制再作成（必要時）
    if os.getenv("CQ_REBUILD_DB", "0") == "1":
        need = True

    if need:
        # 既存があれば削除してクリーンに再生成（スキーマ確実化）
        try:
            if db.exists():
                db.unlink()
        except Exception:
            pass
        _run_import(jsonl, db)

_ensure_db()
# =============================== ここからUI ===============================


# =============================== ここからUI ===============================

import streamlit as st

# --- ページ設定（最初のStreamlit呼び出しで実行すること） ---
st.set_page_config(page_title="CQ App (MVP)", page_icon="🎧", layout="centered")

# --- 以降の依存（両対応インポート） ---
try:
    from app.services.db import load_questions
    from app.services.grader import grade_mcq, grade_sjt
    from app.services.ai_eval import eval_free_response
except ModuleNotFoundError:
    # 実行ディレクトリが app/ などの場合のフォールバック
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from services.db import load_questions
    from services.grader import grade_mcq, grade_sjt
    from services.ai_eval import eval_free_response

from typing import List, Set

st.title("🎧 CQ アプリ（MVP）")

# 黒文字＆引用スタイル
st.markdown("""
<style>
.stMarkdown p, .stMarkdown blockquote, .stMarkdown li, .stMarkdown span { color: #000000 !important; }
blockquote {
  font-size: 1.05rem; line-height: 1.8; color: #000000 !important;
  margin: 0.2rem 0 0.8rem 0; border-left: 4px solid #ccc; padding-left: 0.8rem; background-color: #fafafa;
}
</style>
""", unsafe_allow_html=True)

# -------------------------------
# ヘルパー
# -------------------------------
def domain_tagset(domain_label: str) -> Set[str]:
    """ドメイン選択に応じた優先タグ集合（厳格）"""
    if domain_label == "ビジネス":
        return {"business", "workplace", "meeting", "team", "office", "review", "deadline", "decision"}
    else:  # 日常
        return {"daily", "日常", "friend", "family", "生活", "home", "communication"}

def filter_by_domain_strict(qs, domain_label: str, want: int) -> List:
    """指定ドメインのタグに一致する問題のみを返す（不足分の越境補充はしない）"""
    pref = domain_tagset(domain_label)
    matched = [q for q in qs if any(t in pref for t in (q.tags or []))]
    return matched[:want]

def render_prompt_block(text: str):
    """会話や長文を読みやすく描画（引用＋改行維持。HTMLラップしない）"""
    if not text:
        return
    # 「 A:」「 B:」「 C:」の直前に空行を入れる（視認性UP）
    text = (text
            .replace(" A:", "\n\nA:")
            .replace(" B:", "\n\nB:")
            .replace(" C:", "\n\nC:"))
    # Markdownで改行を維持するため行末に半角スペース2つ
    lines = [ln.rstrip() + "  " for ln in text.split("\n")]
    body = "\n".join([f"> {ln}" if ln else ">" for ln in lines])

    with st.container(border=True):
        st.markdown("#### 🗣️ 設問（本文）")
        st.markdown(body)

def clear_answer_widgets():
    for k in list(st.session_state.keys()):
        s = str(k)
        if s.startswith("q_") or s.startswith("free_"):
            del st.session_state[k]

# -------------------------------
# アプリ説明（折りたたみ）
# -------------------------------
with st.expander("このアプリの説明", expanded=False):
    st.markdown(
        "このアプリは **文脈理解力（CQ: Context Quotient）** を鍛えるアプリの試作版です。\n\n"
        "【使い方】\n"
        "1) ドメイン（ビジネス／日常）とカテゴリを選ぶ → 2問が出題されます。\n"
        "2) 選択式のカテゴリは「採点する」で正誤と解説を確認できます。\n"
        "3) **状況判断**は正解を出さず、選択の文脈解説＋**自由記述**をAIが評価します。\n"
        "4) 下部の **「次の問題を解く（2問）」** で新しい2問が出題されます。"
    )

# -------------------------------
# ドメイン／カテゴリ選択
# -------------------------------
colD, colS = st.columns([1, 1])
with colD:
    domain = st.selectbox("出題ドメイン", ("ビジネス", "日常"), index=0)
with colS:
    skill = st.selectbox(
        "カテゴリ",
        ("要約", "意図理解", "印象マネジメント", "状況判断"),
        index=0
    )

# -------------------------------
# セッション初期化
# -------------------------------
if "current_skill" not in st.session_state:
    st.session_state.current_skill = None
if "current_domain" not in st.session_state:
    st.session_state.current_domain = None
if "fixed_questions" not in st.session_state:
    st.session_state.fixed_questions = []
if "seen_ids" not in st.session_state:
    st.session_state.seen_ids = set()
if "batch_no" not in st.session_state:
    st.session_state.batch_no = 0
if "_last_loaded_batch_no" not in st.session_state:
    st.session_state._last_loaded_batch_no = -1

# -------------------------------
# バッチ取得
# -------------------------------
def get_new_batch(_skill: str, _domain: str, want: int = 2):
    is_sjt = (_skill == "状況判断")
    picked = []

    candidates = load_questions(skill_filter=_skill, limit=200)
    if is_sjt:
        candidates = [q for q in candidates if q.type == "sjt"]
    else:
        candidates = [q for q in candidates if q.type != "sjt"]

    domain_candidates = filter_by_domain_strict(candidates, _domain, want=want)

    for q in domain_candidates:
        if len(picked) >= want:
            break
        if q.id not in st.session_state.seen_ids:
            picked.append(q)
            st.session_state.seen_ids.add(q.id)

    if len(picked) < want:
        st.warning(
            f"{_domain}×{_skill} の登録問題が不足しています（{len(picked)}/{want}）。"
            " `data/questions.jsonl` に追加して import してください。"
        )
    return picked

# スキル or ドメイン変更検知
if (st.session_state.current_skill != skill) or (st.session_state.current_domain != domain):
    st.session_state.current_skill = skill
    st.session_state.current_domain = domain
    st.session_state.seen_ids = set()
    st.session_state.batch_no = 0
    st.session_state._last_loaded_batch_no = -1
    clear_answer_widgets()

# バッチロード
if st.session_state._last_loaded_batch_no != st.session_state.batch_no:
    clear_answer_widgets()
    qs = get_new_batch(skill, domain, want=2)
    st.session_state.fixed_questions = qs
    st.session_state._last_loaded_batch_no = st.session_state.batch_no

questions = st.session_state.fixed_questions

if not questions:
    st.warning("この条件での登録問題が不足しています。`data/questions.jsonl` に追記して import してください。")
    st.stop()

st.divider()
st.subheader(f"出題：{domain} × {skill}（{len(questions)}問）")

# -------------------------------
# 出題UI
# -------------------------------
answers = []
for i, q in enumerate(questions, start=1):
    st.markdown(f"**Q{i}.**")
    render_prompt_block(q.prompt)

    opts = ["A", "B", "C", "D"][:len(q.choices) if q.choices else 0]

    def fmt(k):
        if q.choices and "ABCD".find(k) != -1 and "ABCD".index(k) < len(q.choices):
            return f"{k}: {q.choices['ABCD'.index(k)]}"
        return k

    key = st.radio(
        "選択肢",
        options=opts,
        format_func=fmt,
        index=None,
        horizontal=False,
        key=f"q_{q.id}"
    )
    answers.append(key)

    if skill == "状況判断":
        st.text_area(
            "自由記述（任意）: あなたならどう対応しますか？",
            key=f"free_{q.id}",
            placeholder="例）先方へ初動の方針と目安時間を即共有し、再現条件を確認します…",
            height=110
        )

    st.markdown("---")

# -------------------------------
# 採点／フィードバック
# -------------------------------
is_sjt_mode = (skill == "状況判断")

if is_sjt_mode:
    if st.button("フィードバックを見る", type="primary", use_container_width=True):
        feedbacks = grade_sjt(questions, answers)
        for i, (q, fb) in enumerate(zip(questions, feedbacks), start=1):
            st.markdown(f"### Q{i}")
            with st.container(border=True):
                st.markdown("**シナリオ（再掲）**")
                render_prompt_block(q.prompt)

            st.markdown(f"**あなたの選択:** 🟢 {fb['chosen'] or '—'}")

            st.markdown("#### 各選択肢の解説")
            for key in ["A", "B", "C", "D"]:
                if q.feedbacks and key in q.feedbacks:
                    fbt = q.feedbacks[key]
                    line = f"{key}: {fbt.get('type','—')} — {fbt.get('desc','—')}"
                    if fb["chosen"] == key:
                        st.markdown(f"**👉 {line}**")
                    else:
                        st.markdown(line)

            user_free = (st.session_state.get(f"free_{q.id}") or "").strip()
            if user_free:
                ai = eval_free_response(q.prompt, user_free)
                st.markdown("#### 自由記述へのAIフィードバック")
                st.markdown(f"**あなたの回答:**\n> {user_free}")
                st.write(f"- スコア: {ai.get('score_total', 0)} / 100")
                subs = ai.get("subscores", {}) or {}
                st.write(
                    f"- 文脈適合度: {subs.get('context_fit', 0)} / "
                    f"対人配慮: {subs.get('interpersonal_sensitivity', 0)} / "
                    f"明瞭さ: {subs.get('clarity', 0)}"
                )
                st.write(f"- 要点指摘: {ai.get('short_feedback', '—')}")
                st.write(f"- 次ドリル: {ai.get('next_drill', '—')}")
            st.markdown("---")

        st.info("※ 状況判断は正誤を出さず、各選択肢の解説と自由記述AI評価を提示します。")

else:
    if st.button("採点する", type="primary", use_container_width=True):
        results, correct, total = grade_mcq(questions, answers)
        st.success(f"スコア：{correct} / {total}（{round(100 * correct / total)} 点）")

        with st.expander("各問の解説・正答"):
            for i, r in enumerate(results, start=1):
                st.markdown(
                    f"**Q{i}**：{'✅ 正解' if r.is_correct else ('❌ 不正解' if r.is_correct is not None else '— 未回答')}"
                )
                st.write(f"- あなたの選択: {r.chosen or '—'}")
                st.write(f"- 正答: {r.correct_key or '—'}")

                q = questions[i - 1]
                st.markdown("**解説（選択肢別）**")
                ex_dict = q.explanations or {}
                rendered_any = False
                for key in ["A", "B", "C", "D"]:
                    if key in ex_dict and ex_dict[key]:
                        line = f"{key}: {ex_dict[key]}"
                        if key == (r.correct_key or ""):
                            st.markdown(f"**👉 {line}**")
                        else:
                            st.markdown(line)
                        rendered_any = True

                if not rendered_any:
                    if r.explanation:
                        st.write(f"- 根拠: {r.explanation}")
                    else:
                        st.write("（この問題には解説が登録されていません）")

                st.markdown("---")

# -------------------------------
# 次の2問ボタン
# -------------------------------
st.divider()
if st.button("次の問題を解く（2問）", type="secondary", use_container_width=True):
    st.session_state.batch_no += 1
    st.rerun()
