from dataclasses import dataclass
from typing import List, Optional, Dict

@dataclass
class Question:
    id: str
    skill: str            # 要約 / 意図理解 / 構成 / 印象マネジメント / 状況判断
    level: str            # beginner / advanced（当面beginner）
    type: str             # mcq / free（当面mcq）
    prompt: str
    choices: Optional[List[str]]  # mcqは必須
    answer_key: Optional[str]     # 'A'~'D'
    explanations: Optional[Dict[str, str]]
    difficulty: float
    tags: Optional[List[str]] = None

@dataclass
class AttemptResult:
    question_id: str
    chosen: Optional[str]      # 'A'~'D'
    is_correct: Optional[bool]
    correct_key: Optional[str]
    explanation: Optional[str]
from dataclasses import dataclass
from typing import List, Optional, Dict

@dataclass
class Question:
    id: str
    skill: str            # 要約 / 意図理解 / 構成 / 印象マネジメント / 状況判断
    level: str            # beginner / advanced
    type: str             # mcq / sjt / free
    prompt: str
    choices: Optional[List[str]]
    answer_key: Optional[str]     # mcqのみ 'A'~'D'
    explanations: Optional[Dict[str, str]]
    difficulty: float
    tags: Optional[List[str]] = None
    # ▼ SJT用（選択肢キー 'A','B','C','D' に対応）
    feedbacks: Optional[Dict[str, Dict[str, str]]] = None

@dataclass
class AttemptResult:
    question_id: str
    chosen: Optional[str]      # 'A'~'D'
    is_correct: Optional[bool] # SJTでは常にNone
    correct_key: Optional[str]
    explanation: Optional[str]
