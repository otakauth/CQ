import sys, os, re
from typing import List, Set
from pathlib import Path
import streamlit as st

# --- パス設定（app/ 下で services を import できるように） ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# === services モジュール ===
from services.db import load_questions
from services.grader import grade_mcq, grade_sjt
from services.ai_eval import eval_free_response  # 自由記述のAI評価
from services.ai_eval import gen_session_feedback  # セッション講評生成


# === DBが無ければJSONLから自動作成するセットアップ ===
# どっちの構成でも動くように両対応インポート
try:
    from app.services import import_jsonl as _imp
except Exception:
    from services import import_jsonl as _imp  # 旧構成向け

try:
    # config がある構成
    from app.services.config import DB_PATH, JSONL_PATH
except Exception:
    # config が無い構成のフォールバック
    DB_PATH = Path("data/cq.db")
    JSONL_PATH = Path("data/questions.jsonl")

 # --- DEVメッセージ制御（ユーザーに見せない） ---
def _get_query_params_safe():
    try:
        return st.query_params  # Streamlit 1.27+
    except Exception:
        try:
            return st.experimental_get_query_params()  # 古い互換
        except Exception:
            return {}

_QP = _get_query_params_safe()
DEBUG_DEV = (os.getenv("CQ_DEBUG", "0") == "1") or (_QP.get("debug", ["0"])[0] == "1")

def dev_notice(msg: str):
    """開発者だけが気づける場所に出す（UIには出さない）"""
    if DEBUG_DEV:
        st.warning(msg)
    else:
        print(f"[DEV ONLY] {msg}")
   
# --- Streamlit Cloud対応: data/cq.db を /tmp にコピー ---
import shutil
from pathlib import Path

local_db = Path("data/cq.db")
# --- Cloud用DBコピー（config側で処理済みのため、ここでは安全にスキップ） ---
import os, shutil, tempfile
from pathlib import Path

# 既存の data/cq.db を基準に動作（ローカルでは /tmp を使わない）
local_db = Path("data/cq.db")
_tmpdir = Path(tempfile.gettempdir())

# Linux（Streamlit Cloudなど）でのみコピーを試みる
if os.name == "posix":
    tmp_db = _tmpdir / "cq.db"
    if (not tmp_db.exists()) and local_db.exists():
        try:
            shutil.copy(local_db, tmp_db)
            print("✅ Copied DB to /tmp for Streamlit Cloud")
        except Exception:
            pass  # ⚠️ ローカルWindowsでは無視（ログ出さない）


def _ensure_db():
    """
    DBが無い/空/古い場合に JSONL→DB を実行する。
    環境変数 FORCE_IMPORT=1 があれば強制再インポート。
    Streamlit Cloud など一時環境では DB が存在しないことがあるため、
    無くても常に安全に再生成できるようにしている。
    """
    jsonl = Path(JSONL_PATH)
    db = Path(DB_PATH)

    need = False

    # 強制フラグ
    if os.getenv("FORCE_IMPORT", "0") == "1":
        need = True

    # DBが無い/小さすぎる
    if not db.exists():
        need = True
    else:
        try:
            if db.stat().st_size < 1024:
                need = True
        except Exception:
            need = True

    # JSONL が DB より新しければ再インポート
    if not need:
        try:
            if jsonl.exists() and jsonl.stat().st_mtime > db.stat().st_mtime:
                need = True
        except Exception:
            need = True

    if need:
        # import_jsonl.py の関数名両対応
        if hasattr(_imp, "run"):
            _imp.run(str(jsonl), str(db))
        elif hasattr(_imp, "import_jsonl"):
            _imp.import_jsonl()
        else:
            raise RuntimeError("import_jsonl.py に run() も import_jsonl() も見つかりません。")
    else:
        # ✅ Cloud環境でDBが存在しないときの安全対策（暫定）
        # デプロイ直後に /tmp や data/ が空の場合、毎回JSONLから再生成する
        try:
            if not db.exists() or db.stat().st_size < 1024:
                if hasattr(_imp, "run"):
                    _imp.run(str(jsonl), str(db))
                elif hasattr(_imp, "import_jsonl"):
                    _imp.import_jsonl()
        except Exception as e:
            print(f"[WARN] 強制再生成失敗: {e}")

_ensure_db()


# === セットアップここまで ===

# --- ページ設定 ---
st.set_page_config(page_title="CQ App (MVP)", page_icon="🎧", layout="centered")
st.title("🎧 CQ アプリ（MVP）")
# ▼通算リセットボタン
if st.button("🧹 通算をリセット", help="回をまたいだ講評履歴を消去します"):
    st.session_state.history_items = []
    st.success("通算データをリセットしました。")

# --- 見た目調整（黒文字＆引用ブロック） ---
st.markdown("""
<style>
/* 全体のテキストを黒寄りに */
.stMarkdown p, .stMarkdown blockquote, .stMarkdown li, .stMarkdown span {
  color: #111 !important;
}

/* 引用ブロック（> A: など） */
blockquote {
  font-size: 1.05rem;
  line-height: 1.8;
  color: #111 !important;
  margin: 0.2rem 0 0.8rem 0;
  border-left: 4px solid #ccc;
  padding-left: 0.8rem;
  background-color: #fafafa;
}
</style>
""", unsafe_allow_html=True)

# -------------------------------
# ヘルパー
# -------------------------------
def _render_session_summary(summary: dict | None):
    # 安全化：None や想定外型でも落とさない
    if not isinstance(summary, dict) or not summary:
        st.info("まだ通算データがありません。")
        return

    scores = summary.get("skill_scores", {}) or {}
    st.markdown("**スキル別スコア**")
    for k, v in scores.items():
        try:
            st.markdown(f"- {k}: {float(v):.2f}")
        except Exception:
            st.markdown(f"- {k}: {v}")

    def _bullets(title, key):
        items = summary.get(key) or []
        if not items:
            return
        st.markdown(f"**{title}**")
        for x in items:
            st.markdown(f"- {x}")

    _bullets("特徴", "traits")
    _bullets("強み", "strengths")
    _bullets("弱み", "weaknesses")
    _bullets("次アクション", "next_actions")

    recs = summary.get("recommended_drills") or []
    if recs:
        st.markdown("**おすすめドリル**")
        for d in recs:
            skill = d.get("skill", "")
            level = d.get("level", "")
            tags  = ", ".join(d.get("tags") or [])
            why   = d.get("why", "")
            st.markdown(f"- {skill}（{level}）｜{tags} — {why}")


def domain_tagset(domain_label: str) -> Set[str]:
    """ドメイン選択に応じた優先タグ集合"""
    if domain_label == "ビジネス":
        return {"business", "workplace", "meeting", "team", "office", "review", "deadline", "decision"}
    else:  # 日常
        return {"daily", "日常", "friend", "family", "生活", "home", "communication"}

def filter_by_domain_strict(qs, domain_label: str, want: int) -> List:
    """タグ一致のみ採用（越境補充なし）"""
    pref = domain_tagset(domain_label)
    matched = [q for q in qs if any(t in pref for t in (q.tags or []))]
    return matched[:want]

def render_prompt_block(text: str):
    """会話や長文を読みやすく描画（引用＋改行維持、A:/B:の前に空行）"""
    if not text:
        return

    # 「 A:」「 B:」「 C:」の直前に空行を入れる（文頭/直後どちらでも機能）
    text = re.sub(r'\s+A:', '\n\nA:', text)
    text = re.sub(r'\s+B:', '\n\nB:', text)
    text = re.sub(r'\s+C:', '\n\nC:', text)

    # Markdown改行維持（行末半角スペース2つ）
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
# 上部UI：アプリ説明（閉じられる）
# -------------------------------
with st.expander("このアプリの説明", expanded=False):
    st.markdown(
        "このアプリは **文脈理解力（CQ: Context Quotient）** を鍛えるアプリの試作版です。\n\n"
        "【使い方】\n"
        "1) ドメイン（ビジネス／日常）とカテゴリを選ぶ → 2問が出題されます。\n"
        "2) 選択式は「採点する」で正誤と解説を確認できます。\n"
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
# 回を跨いだ通算の履歴（各問の成績をここに貯める）
if "history_items" not in st.session_state:
    st.session_state.history_items = []
# --- 採点状態フラグと講評の一時保持 ---
if "_graded" not in st.session_state:
    st.session_state._graded = False
if "_ai_summary" not in st.session_state:
    st.session_state._ai_summary = None
if "_ai_summary_total" not in st.session_state:
    st.session_state._ai_summary_total = None

# -------------------------------
# バッチ取得
# -------------------------------
def get_new_batch(_skill: str, _domain: str, want: int = 2):
    """
    指定スキル／ドメインから未出題の問題を最大 want 件返す。
    在庫不足時はユーザー向けUIには出さず、開発者向けに dev_notice だけ出す。
    """
    is_sjt = (_skill == "状況判断")
    picked = []

    # 多めに取得 → タイプで絞る
    candidates = load_questions(skill_filter=_skill, limit=200)
    if is_sjt:
        candidates = [q for q in candidates if q.type == "sjt"]
    else:
        candidates = [q for q in candidates if q.type != "sjt"]

    # ドメイン厳格フィルタ（越境補充なし）
    domain_candidates = filter_by_domain_strict(candidates, _domain, want=want)

    # 未出題のみを pick
    seen = st.session_state.get("seen_ids", set())
    for q in domain_candidates:
        if len(picked) >= want:
            break
        if q.id not in seen:
            picked.append(q)
            seen.add(q.id)
    st.session_state["seen_ids"] = seen

    # 在庫不足は DEV だけ通知（UIには出さない）
    if len(picked) < want:
        dev_notice(
            f"{_domain}×{_skill} の登録問題が不足しています（{len(picked)}/{want}）。"
            " data/questions.jsonl に追加して import してください。"
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
# 新しいバッチに切り替わったので採点状態と講評をリセット
st.session_state._graded = False
st.session_state._ai_summary = None
st.session_state._ai_summary_total = None

questions = st.session_state.fixed_questions

if not questions:
    dev_notice("この条件での登録問題が不足しています。data/questions.jsonl に追記して import してください。")
    # ユーザーには汎用の優しい文言のみ
    st.info("この条件の問題はもうないよ。別のドメイン/カテゴリをお試しください。")
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
    if st.session_state.get("_graded", False):
        st.info("このバッチは採点済みです。下部の「次の問題を解く（2問）」で新バッチに進めます。")
    elif st.button("フィードバックを見る", type="primary", use_container_width=True):

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

        # ===== セッション講評（AI：状況判断） =====
        from services.ai_eval import gen_session_feedback

        # ① 自由記述の評価キャッシュ（表示用と集計用で使い回し）
        _free_cache: dict[str, dict] = {}

        session_items = []
        for q, fb in zip(questions, feedbacks):
            # 自由記述スコア（0..1）— 二重評価を避ける
            user_free = (st.session_state.get(f"free_{q.id}") or "").strip()
            free_score01 = 0.0
            if user_free:
                ai = _free_cache.get(q.id)
                if not ai:
                    ai = eval_free_response(q.prompt, user_free)
                    _free_cache[q.id] = ai
                free_score01 = ai.get("score_total", 0) / 100.0

            # skill 正規化（全角/半角スペース除去）
            skill_norm = (q.skill or "").replace(" ", "").replace("　", "")

            # 望ましい選択 best（answer_key 優先、なければ feedbacks の type を参照）
            best_key = getattr(q, "answer_key", None)
            if not best_key and getattr(q, "feedbacks", None):
                try:
                    best_key = next(
                        (k for k, v in q.feedbacks.items() if (v or {}).get("type") in ("best", "good")),
                        None
                    )
                except Exception:
                    best_key = None

            # ② 未判定（best/chosen が無い）を 0 点計上せずスキップ
            #    ※ 自由記述があれば free_score01 だけで反映する
            item = {
                "id": q.id,
                "type": q.type,          # "sjt"
                "skill": skill_norm,
                "tags": q.tags or [],
                "free_score01": free_score01,
                "chosen": fb.get("chosen"),
                "best": best_key,
            }
            if (item["best"] is None or item["chosen"] is None) and free_score01 == 0.0:
                # 選択評価も自由記述も無い → 平均を歪めるので除外
                continue

            session_items.append(item)
        st.session_state.history_items.extend(session_items)

        print("DEBUG session_items:", session_items)
        summary = gen_session_feedback(session_items)
# 採点完了フラグとAI講評キャッシュを更新（SJT）
        st.session_state._graded = True
        st.session_state._ai_summary = summary
        st.session_state._ai_summary_total = None

        # ③ JSON“そのまま出力”ではなく、箇条書きでレンダリング
        def _render_session_summary(summary: dict):
            scores = summary.get("skill_scores", {}) or {}
            st.markdown("**スキル別スコア**")
            for k, v in scores.items():
                try:
                    st.markdown(f"- {k}: {float(v):.2f}")
                except Exception:
                    st.markdown(f"- {k}: {v}")

            def _bullets(title, key):
                items = summary.get(key) or []
                if not items:
                    return
                st.markdown(f"**{title}**")
                for x in items:
                    st.markdown(f"- {x}")

            _bullets("特徴", "traits")
            _bullets("強み", "strengths")
            _bullets("弱み", "weaknesses")
            _bullets("次アクション", "next_actions")

            recs = summary.get("recommended_drills") or []
            if recs:
                st.markdown("**おすすめドリル**")
                for d in recs:
                    skill = d.get("skill", "")
                    level = d.get("level", "")
                    tags  = ", ".join(d.get("tags") or [])
                    why   = d.get("why", "")
                    st.markdown(f"- {skill}（{level}）｜{tags} — {why}")

# （SJT専用）採点後のみAI講評ボタンを表示（デフォ表示防止＆二重表示防止）
if is_sjt_mode and st.session_state.get("_graded", False) and st.session_state.get("history_items"):
    if st.button("🧠 AI講評を見る", type="secondary", use_container_width=True, key=f"ai_summary_btn_sjt_{st.session_state.batch_no}"):

        # ✅ 通算のみ表示（セッション講評は出さない）
        total_payload = {"session_items": st.session_state.history_items}
        summary_total = gen_session_feedback(total_payload)
        st.session_state._ai_summary_total = summary_total
        with st.expander("🧠 AI講評（通算）", expanded=True):
            _render_session_summary(summary_total)









if not is_sjt_mode:
    if st.session_state.get("_graded", False):
        st.info("このバッチは採点済みです。下部の「次の問題を解く（2問）」で新バッチに進めます。")
    elif st.button("採点する", type="primary", use_container_width=True):

 
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
                    st.write("（この問題には解説が登録されていません）")
                st.markdown("---")

        # ===== セッション講評（AI：選択式） =====
        from services.ai_eval import gen_session_feedback
        from collections import defaultdict

        # ① 今バッチの成績だけで、0/1 の厳密平均を作る（未回答は除外）
        session_items = []
        per_skill_correct = defaultdict(int)
        per_skill_total   = defaultdict(int)

        for r, q in zip(results, questions):
            skill_norm = (q.skill or "").replace(" ", "").replace("　", "")

            # 未回答は除外（平均を歪めない）
            if r.is_correct is None and not r.chosen:
                continue

            # 0/1カウント（MCQのみ）
            if r.is_correct is True:
                per_skill_correct[skill_norm] += 1
                per_skill_total[skill_norm]   += 1
            elif r.is_correct is False:
                per_skill_total[skill_norm]   += 1

            session_items.append({
                "id": q.id,
                "type": q.type,          # "mcq"
                "skill": skill_norm,
                "difficulty": q.difficulty,
                "tags": q.tags or [],
                "correct": r.is_correct,
                "chosen": r.chosen,
                "answer_key": r.correct_key
            })

        # ② スキル別の正解率（0..1）を事前計算して LLM に手渡す
        pre_skill_scores = {}
        for sk, tot in per_skill_total.items():
            if tot > 0:
                pre_skill_scores[sk] = round(per_skill_correct[sk] / tot, 2)

        # ③ 正解数/全問数も渡す（未回答は全問数に含めない）
        correct_count = sum(1 for r in results if r.is_correct is True)
        total_count   = len([r for r in results if r.is_correct is not None])

        payload = {
            "session_items": session_items,
            "meta": {
                "correct": correct_count,
                "total": total_count,
                "pre_skill_scores": pre_skill_scores,   # ←これを尊重させる
            }
        }
        st.session_state._last_payload = payload  # ← AI講評ボタン用に保持

        st.session_state.history_items.extend(session_items)
        
        print("DEBUG session_items:", session_items)
        print("DEBUG meta:", payload["meta"])

# 採点完了フラグのみ立て、AI講評はまだ生成しない
st.session_state._graded = True
st.session_state._ai_summary = None
st.session_state._ai_summary_total = None

# ボタン押下時のみAI講評を生成・表示
if (not is_sjt_mode) and st.session_state.get("history_items") and st.button(
    "🧠 AI講評を見る", type="secondary", use_container_width=True, key=f"ai_summary_btn_mcq_{st.session_state.batch_no}"
):

    # ✅ 通算だけを生成・表示（セッション講評は出さない）
    total_payload = {"session_items": st.session_state.history_items}
    summary_total = gen_session_feedback(total_payload)
    st.session_state._ai_summary_total = summary_total
    with st.expander("🧠 AI講評（通算）", expanded=True):
        _render_session_summary(summary_total)

# -------------------------------
# 次の2問ボタン
# -------------------------------

st.divider()
if st.button("次の問題を解く（2問）", type="secondary", use_container_width=True):
    # 採点状態とAI講評を完全リセット
    st.session_state._graded = False
    st.session_state._ai_summary = None
    st.session_state._ai_summary_total = None
    st.session_state.batch_no += 1
    st.rerun()

