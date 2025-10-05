# app/services/ai_eval.py
import os, json, re
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

# --- OpenAI クライアントの用意（無ければ None → ルールベースでフォールバック） ---
_openai_client = None
try:
    from openai import OpenAI
    if os.getenv("OPENAI_API_KEY"):
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception:
    _openai_client = None


SYSTEM_PROMPT = """あなたはビジネスコミュニケーションの講師です。
回答を以下の観点で評価し、必ず次のJSON形式のみを返してください（日本語）:
{
  "score_total": 0-100の整数,
  "subscores": {
    "context_fit": 0-100の整数,                 // 文脈適合度
    "interpersonal_sensitivity": 0-100の整数,   // 対人配慮
    "clarity": 0-100の整数                      // 明瞭さ
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
    """
    OpenAIの出力や他形式を、UIが期待するスキーマに正規化する。
    期待スキーマ:
      score_total(int), subscores{context_fit, interpersonal_sensitivity, clarity}, short_feedback(str), next_drill(str)
    """
    # 直接マッチ（理想）
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

    # 別名からのマッピング（以前の実装との互換）
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
    t = txt.lower()

    score = 60
    context_fit = 60
    interpersonal = 60
    clarity = 60

    # 明確なNGワード・態度（大幅減点）
    negative_triggers = ["怒る", "キレる", "責める", "無視", "放置", "罰する", "文句", "遅い", "あり得ない"]
    if any(w in txt for w in negative_triggers):
        interpersonal -= 40
        context_fit -= 20
        score -= 30

    # 良い要素があれば加点
    good_signals = ["事情", "確認", "代替", "再調整", "共有", "合意", "期限", "目安", "方針", "謝罪", "連絡"]
    if any(w in txt for w in good_signals):
        context_fit += 10
        clarity += 10
        score += 10

    # 長さ（少なすぎると減点）
    if len(txt.strip()) < 8:
        clarity -= 20
        score -= 10

    # クリップ
    context_fit = max(0, min(100, context_fit))
    interpersonal = max(0, min(100, interpersonal))
    clarity = max(0, min(100, clarity))
    score = max(0, min(100, score))

    return {
        "score_total": score,
        "subscores": {
            "context_fit": context_fit,
            "interpersonal_sensitivity": interpersonal,
            "clarity": clarity
        },
        "short_feedback": "感情的な反応は関係悪化のリスク。まず事情確認と代替案提示で建設的に進めましょう。",
        "next_drill": "相手の事情確認→決められる範囲の前進合意→次の連絡時刻、の3点を1文で述べてみてください。"
    }

def eval_free_response(prompt_text: str, user_text: str) -> Dict[str, Any]:
    """
    シナリオ（prompt_text）とユーザー回答（user_text）を評価し、
    UIが期待するスキーマで返す。
    """
    # 入力が短すぎる場合の即時応答
    if not user_text or len(user_text.strip()) < 3:
        return {
            "score_total": 0,
            "subscores": {
                "context_fit": 0,
                "interpersonal_sensitivity": 0,
                "clarity": 0
            },
            "short_feedback": "入力が短すぎます。あなたの初動（何を・誰に・いつ）を1〜2文で書いてください。",
            "next_drill": "相手の事情確認と代替案提示を1文で書いてみましょう。"
        }

    # OpenAIが使えない場合は即フォールバック
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
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        content = resp.choices[0].message.content.strip()

        # JSON抽出の保険（テキストに余計な文が入った場合）
        # 最初の { から最後の } までを抜く
        m = re.search(r"\{.*\}", content, flags=re.S)
        json_str = m.group(0) if m else content

        data = json.loads(json_str)
        return _to_ui_schema(data)

    except Exception:
        # モデルエラー・JSONパース失敗時はルールベースへ
        return _fallback_rule_based(prompt_text, user_text)
