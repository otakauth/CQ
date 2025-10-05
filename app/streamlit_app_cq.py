import streamlit as st
import sys, os
from typing import List, Set

# --- パス設定 ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.db import load_questions
from services.grader import grade_mcq, grade_sjt
from services.ai_eval import eval_free_response  # 自由記述のAI評価

# --- ページ設定 ---
st.set_page_config(page_title="CQ App (MVP)", page_icon="🎧", layout="centered")

st.title("🎧 CQ アプリ（MVP）")
st.caption("各カテゴリ：2問ずつ出題。状況判断は選択別フィードバック＋自由記述AI評価。")

# -------------------------------
# ヘルパー
# -------------------------------
def domain_tagset(domain_label: str) -> Set[str]:
    """ドメイン選択に応じた優先タグ集合"""
    if domain_label == "ビジネス":
        return {"workplace", "meeting", "team", "business", "office", "review", "deadline", "decision"}
    else:  # 日常
        return {"daily", "日常", "friend", "family", "生活", "home", "communication"}

def filter_by_domain(qs, domain_label: str):
    """タグ一致を優先、足りなければ全体から補充"""
    pref = domain_tagset(domain_label)
    matched = [q for q in qs if any(t in pref for t in (q.tags or []))]
    if len(matched) >= 2:
        return matched
    # 不足ぶんは全体から埋める
    seen_ids = {q.id for q in matched}
    for q in qs:
        if len(matched) >= 2:
            break
        if q.id not in seen_ids:
            matched.append(q)
            seen_ids.add(q.id)
    return matched

def render_prompt_block(text: str):
    """会話や長文を読みやすく描画（引用・強制改行）"""
    # Markdownの改行は "  \n" が必要。各行を引用に。
    lines = [ln.strip() for ln in (text or "").split("\n")]
    body = "\n".join([f"> {ln}" if ln else ">" for ln in lines])
    with st.container(border=True):
        st.markdown("**設問（本文）**")
        st.markdown(body)

def clear_answer_widgets():
    for k in list(st.session_state.keys()):
        s = str(k)
        if s.startswith("q_") or s.startswith("free_"):
            del st.session_state[k]

# -------------------------------
# 上部UI：アプリ説明
# -------------------------------
col1, col2 = st.columns([1, 1])
with col1:
    show_info = st.button("このアプリの説明", use_container_width=True)
with col2:
    pass  # 余白

if show_info:
    st.info(
        "このアプリは **文脈理解力（CQ: Context Quotient）** を鍛えるためのアプリの試作版です。\n\n"
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

def get_new_batch(_skill: str, _domain: str, want: int = 2):
    is_sjt = (_skill == "状況判断")
    picked = []

    # 多めに引いてからドメインで絞る→未出題で詰める
    candidates = load_questions(skill_filter=_skill, limit=30)
    if is_sjt:
        candidates = [q for q in candidates if q.type == "sjt"]
    else:
        candidates = [q for q in candidates if q.type != "sjt"]

    # ドメイン優先
    candidates = filter_by_domain(candidates, _domain)

    # 未出題のみ
    for q in candidates:
        if len(picked) >= want:
            break
        if q.id not in st.session_state.seen_ids:
            picked.append(q)
            st.session_state.seen_ids.add(q.id)

    # それでも不足なら全体から補充
    if len(picked) < want:
        fallback = load_questions(skill_filter=_skill, limit=30)
        if is_sjt:
            fallback = [q for q in fallback if q.type == "sjt"]
        else:
            fallback = [q for q in fallback if q.type != "sjt"]
        for q in fallback:
            if len(picked) >= want:
                break
            if q.id not in st.session_state.seen_ids:
                picked.append(q)
                st.session_state.seen_ids.add(q.id)

    return picked

# スキル or ドメインが変わったらリセットして最初の2問
if (st.session_state.current_skill != skill) or (st.session_state.current_domain != domain):
    st.session_state.current_skill = skill
    st.session_state.current_domain = domain
    st.session_state.seen_ids = set()
    st.session_state.batch_no = 0
    st.session_state._last_loaded_batch_no = -1
    clear_answer_widgets()

# バッチが未ロードならロード
if st.session_state._last_loaded_batch_no != st.session_state.batch_no:
    clear_answer_widgets()
    qs = get_new_batch(skill, domain, want=2)
    st.session_state.fixed_questions = qs
    st.session_state._last_loaded_batch_no = st.session_state.batch_no

# 以後は固定した問題を使う
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
    render_prompt_block(q.prompt)  # ← 読みやすく表示

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

    # SJTのみ：自由記述欄
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
    # SJT: 正誤なし＋自由記述AI評価
    if st.button("フィードバックを見る", type="primary", use_container_width=True):
        feedbacks = grade_sjt(questions, answers)

        for i, (q, fb) in enumerate(zip(questions, feedbacks), start=1):
            st.markdown(f"### Q{i}")

            with st.container(border=True):
                st.markdown("**シナリオ（再掲）**")
                # 同じ描画関数を再利用
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

            # 自由記述のAI評価（任意）
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

        st.info("※ 状況判断は“正解/不正解”を出さず、各選択肢の文脈解説と自由記述のAI評価（任意）を提示します。")

else:
    # MCQ: 採点＋正誤・根拠（選択肢別の解説一覧）
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
