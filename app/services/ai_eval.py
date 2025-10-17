import os, json, re
from typing import Dict, Any
from app.services.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

# --- OpenAI クライアント（無ければ None → ルールベースにフォールバック） ---
_openai_client = None
try:
    from openai import OpenAI
    if OPENAI_API_KEY:
        # base_url は空文字なら None を渡して公式エンドポイントを利用
        _openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=(OPENAI_BASE_URL or None))
except Exception:
    _openai_client = None

SYSTEM_PROMPT = """あなたはビジネスコミュニケーションの講師です。
回答を以下の観点で評価し、必ず次のJSON形式のみを返してください（日本語）:
{
  "score_total": 0-100の整数,
  "subscores": {
    "context_fit": 0-100の整数,
    "interpersonal_sensitivity": 0-100の整数,
    "clarity": 0-100の整数
  },
  "short_feedback": "1-2文の講評（改行なし）",
  "next_drill": "次に行うと良い練習を1文（改行なし）"
}
採点方針:
- 感情的・攻撃的・責任転嫁は「対人配慮」を大きく減点
- 事情確認→方針提示→合意形成があれば「文脈適合度」を加点
- 具体的な手順・主体・期限があれば「明瞭さ」を加点
"""

def _to_ui_schema(data: Dict[str, Any]) -> Dict[str, Any]:
    if "score_total" in data and "subscores" in data:
        ss = data.get("subscores", {}) or {}
        return {
            "score_total": int(data.get("score_total", 0) or 0),
            "subscores": {
                "context_fit": int(ss.get("context_fit", 0) or 0),
                "interpersonal_sensitivity": int(ss.get("interpersonal_sensitivity", 0) or 0),
                "clarity": int(ss.get("clarity", 0) or 0),
            },
            "short_feedback": (data.get("short_feedback") or "").strip() or "改善点を1つ具体化しましょう。",
            "next_drill": (data.get("next_drill") or "").strip() or "事情確認と代替案提示を1文で書いてみてください。"
        }
    return {
        "score_total": int(data.get("score") or 0),
        "subscores": {
            "context_fit": int(data.get("context") or data.get("context_fit") or 0),
            "interpersonal_sensitivity": int(data.get("empathy") or data.get("interpersonal_sensitivity") or 0),
            "clarity": int(data.get("clarity") or 0),
        },
        "short_feedback": (data.get("comment") or data.get("short_feedback") or "").strip() or "要点をもう少し具体的に書いてください。",
        "next_drill": (data.get("next") or data.get("next_drill") or "").strip() or "相手の事情確認と対応方針を1文でまとめてみましょう。"
    }

def _fallback_rule_based(prompt_text: str, user_text: str) -> Dict[str, Any]:
    txt = user_text or ""
    score = 60; context_fit = 60; interpersonal = 60; clarity = 60
    if any(w in txt for w in ["怒る", "キレる", "責める", "無視", "放置", "罰する", "文句", "遅い", "あり得ない"]):
        interpersonal -= 40; context_fit -= 20; score -= 30
    if any(w in txt for w in ["事情", "確認", "代替", "再調整", "共有", "合意", "期限", "目安", "方針", "謝罪", "連絡"]):
        context_fit += 10; clarity += 10; score += 10
    if len(txt.strip()) < 8:
        clarity -= 20; score -= 10
    clip = lambda v: max(0, min(100, v))
    return {
        "score_total": clip(score),
        "subscores": {
            "context_fit": clip(context_fit),
            "interpersonal_sensitivity": clip(interpersonal),
            "clarity": clip(clarity)
        },
        "short_feedback": "感情的な反応はリスク。まず事情確認と代替案提示で建設的に進めましょう。",
        "next_drill": "事情確認→前進合意→次の連絡時刻、の3点を1文で述べてください。"
    }

def eval_free_response(prompt_text: str, user_text: str) -> Dict[str, Any]:
    if not user_text or len(user_text.strip()) < 3:
        return {
            "score_total": 0,
            "subscores": {"context_fit": 0, "interpersonal_sensitivity": 0, "clarity": 0},
            "short_feedback": "入力が短すぎます。あなたの初動（何を・誰に・いつ）を1〜2文で書いてください。",
            "next_drill": "相手の事情確認と代替案提示を1文で書いてみましょう。"
        }

    if _openai_client is None:
        return _fallback_rule_based(prompt_text, user_text)

    user_prompt = (
        "次の状況と回答を評価してください。\n\n"
        f"【状況】\n{prompt_text}\n\n"
        f"【回答】\n{user_text}\n\n"
        "必ず上記のJSON形式だけを返してください。"
    )

    try:
        resp = _openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        content = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", content, flags=re.S)
        json_str = m.group(0) if m else content
        data = json.loads(json_str)
        return _to_ui_schema(data)
    except Exception:
        return _fallback_rule_based(prompt_text, user_text)
# === セッション講評（複数問の結果をまとめて評価） =====================

SESSION_SYSTEM_PROMPT = """あなたはビジネスコミュニケーションのコーチです。
与えられた複数問の成績サマリから、受検者の傾向を推定し、必ず次のJSONのみ（日本語）を返してください:
{
  "skill_scores": { "要約": 0〜1の小数, "意図理解": 0〜1, "構成力": 0〜1, "印象マネジメント": 0〜1, "状況判断": 0〜1 },
  "traits": ["短い箇条書き(3-5)"],
  "strengths": ["..."],
  "weaknesses": ["..."],
  "next_actions": ["..."],
  "recommended_drills": [
    {"skill":"...", "level":"beginner|intermediate|advanced", "tags":["..."], "why":"短く"}
  ]
}
出力はJSON以外の文字・前置き・解説を一切含めないこと。
"""

def _fallback_session_profile(session_items: list[dict]) -> dict:
    """LLMなしのときの簡易推定（0..1で集計して所感を返す）"""
    if not session_items:
        return {
            "skill_scores": {},
            "traits": ["データが少ないため推定不能"],
            "strengths": [],
            "weaknesses": [],
            "next_actions": ["まず3問以上を解いてください"],
            "recommended_drills": []
        }

    by_skill = {}
    for it in session_items:
        sk = it.get("skill") or "その他"
        t  = it.get("type")
        if t == "mcq":
            corr = it.get("correct", None)
            if corr is None:
                continue  # 未回答は平均から除外
            val = 1.0 if corr else 0.0

        elif t == "sjt":
            val = 1.0 if it.get("chosen") == it.get("best") else 0.0
        elif t == "free":
            try:
                val = float(it.get("free_score01", 0.0))
            except Exception:
                val = 0.0
        else:
            val = 0.0
        by_skill.setdefault(sk, []).append(val)

    skill_scores = {k: round(sum(v)/len(v), 2) for k, v in by_skill.items() if v}
    avg = round(sum(skill_scores.values())/len(skill_scores), 2) if skill_scores else 0.0

    traits, strengths, weaknesses, next_actions = [], [], [], []

    if avg >= 0.75:
        traits.append("全体的に安定して高い精度")
        strengths.append("要点抽出と選択の一貫性")
        next_actions.append("難易度を一段上げて応用パターンに取り組む")
    elif avg >= 0.5:
        traits.append("基礎は安定、場面によりムラ")
        weaknesses.append("結論先行や根拠の具体性が弱い場面あり")
        next_actions.append("結論→根拠2点の型で60〜120字の練習")
    else:
        traits.append("基礎の取りこぼしが散見")
        weaknesses.append("設問の目的/前提の把握が不足")
        next_actions.append("設問の目的を1行で書き出してから回答を構成")

    if "要約" in skill_scores and skill_scores["要約"] < 0.6:
        weaknesses.append("要約で副次情報に引っ張られやすい")
        next_actions.append("主要3点の箇条書き→1文に圧縮の練習")
    if "構成力" in skill_scores and skill_scores["構成力"] < 0.6:
        weaknesses.append("結論先行と段落内の論理の流れが弱い")
        next_actions.append("結論→理由→相手メリットの順で整形")
    if "状況判断" in skill_scores and skill_scores["状況判断"] < 0.6:
        weaknesses.append("相手の制約/目的を踏まえた選好が弱い")
        next_actions.append("相手の前提・制約を1行で明示してから回答")

    recs = []
    for sk, sc in skill_scores.items():
        if sc < 0.6:
            recs.append({"skill": sk, "level": "beginner", "tags": [], "why": "基礎の型を定着"})
        elif sc < 0.8:
            recs.append({"skill": sk, "level": "intermediate", "tags": [], "why": "応用パターン強化"})
    if not recs:
        recs = [{"skill": "応用セット", "level": "advanced", "tags": [], "why": "高難度で安定性検証"}]

    # 重複除去して上限
    def uniq(xs): return list(dict.fromkeys(xs))
    return {
        "skill_scores": skill_scores,
        "traits": uniq(traits)[:5],
        "strengths": uniq(strengths)[:5],
        "weaknesses": uniq(weaknesses)[:5],
        "next_actions": uniq(next_actions)[:5],
        "recommended_drills": recs[:3],
    }

def gen_session_feedback(session_items: list[dict]) -> dict:


    """
    入力（例・最小）：各問の集計結果
      [{"id":"q1","type":"mcq","skill":"要約","correct":True},
       {"id":"q2","type":"sjt","skill":"状況判断","chosen":"B","best":"B"},
       {"id":"q3","type":"free","skill":"構成力","free_score01":0.62}]
    出力：画面でそのまま表示できる講評オブジェクト
   """
    # --- payload が dict なら展開（meta: 正解数/全問数） ---
    if isinstance(session_items, dict):
        meta = session_items.get("meta", {})
        session_items = session_items.get("session_items", [])
    else:
        meta = {}

    # 正解率の説明テキスト（プロンプトに同封）
    correct_str = ""
    if meta:
        c, t = meta.get("correct"), meta.get("total")
        if c is not None and t:
            try:
                pct = round(100 * c / t)
                correct_str = f"\n全{t}問中{c}問正解（正解率{pct}%）。\n"
            except Exception:
                pass
    # 事前計算されたスキル別スコア（0..1）を受け取る
    pre_skill_scores = {}
    if isinstance(meta, dict):
        pre_skill_scores = meta.get("pre_skill_scores") or {}

    if not session_items:
        return _fallback_session_profile(session_items)

    if _openai_client is None:
        return _fallback_session_profile(session_items)

    user_prompt = (
        "次の複数問の成績サマリから、受検者の傾向を分析してください。\n"
        "必ず指定のJSONスキーマのみを返してください。\n"
        "注意：下記の skill_scores 予測値が与えられた場合は、その値をそのまま採用してください。\n"
        f"{correct_str}"
        f"{json.dumps({'session_items': session_items, 'pre_skill_scores': pre_skill_scores}, ensure_ascii=False)}"
    )


    try:
        resp = _openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SESSION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0
        )
        content = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", content, flags=re.S)
        json_str = m.group(0) if m else content
        data = json.loads(json_str)
        # LLMが出した skill_scores を、事前計算の値で上書き（厳密にする）
        if isinstance(data, dict) and pre_skill_scores:
            data['skill_scores'] = pre_skill_scores


        # 期待キーが無ければフォールバック
        if not isinstance(data, dict) or "skill_scores" not in data:
            return _fallback_session_profile(session_items)
        return data
    except Exception:
        return _fallback_session_profile(session_items)
