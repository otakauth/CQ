from typing import List, Tuple
from app.domain.models import Question, AttemptResult

KEYS = ["A","B","C","D"]

def grade_mcq(questions: List[Question], chosen_keys: List[str]) -> Tuple[List[AttemptResult], int, int]:
    results: List[AttemptResult] = []
    correct = 0
    total = len(questions)
    for q, chosen in zip(questions, chosen_keys):
        chosen = (chosen or "").strip().upper()
        ok = None
        if q.answer_key and chosen in KEYS:
            ok = (chosen == q.answer_key)
            if ok:
                correct += 1
        exp = None
        if q.explanations and q.answer_key:
            exp = q.explanations.get(q.answer_key)
        results.append(AttemptResult(
            question_id=q.id,
            chosen=chosen if chosen in KEYS else None,
            is_correct=ok,
            correct_key=q.answer_key,
            explanation=exp
        ))
    return results, correct, total

# ▼ 追加：状況判断（SJT）— 正誤なし、選択に応じたフィードバックのみ返す
def grade_sjt(questions: List[Question], chosen_keys: List[str]) -> List[dict]:
    out = []
    for q, chosen in zip(questions, chosen_keys):
        key = (chosen or "").strip().upper()
        fb = {"type": "—", "desc": "回答なし"}
        if q.feedbacks and key in q.feedbacks:
            fb = q.feedbacks[key]
        out.append({
            "question_id": q.id,
            "chosen": key if key in KEYS else None,
            "feedback_type": fb.get("type", "—"),
            "feedback_desc": fb.get("desc", "—")
        })
    return out
