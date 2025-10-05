import os
from pathlib import Path
import streamlit as st

def _get(key: str, default: str | None = None) -> str | None:
    # Streamlit Cloud の secrets > 環境変数 > 既定値 の優先
    try:
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)

# 実行環境のざっくり判定（Cloud なら /tmp を使う）
RUN_ENV = _get("CQ_ENV", "local")  # "cloud" または "local"

# OpenAI / 互換API
OPENAI_API_KEY  = _get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = _get("OPENAI_BASE_URL", "")  # 例: https://api.openai.com/v1 や 互換APIのURL
OPENAI_MODEL    = _get("OPENAI_MODEL", "gpt-4o-mini")

# DB パス：ローカルは data/cq.db、Cloud は /tmp/cq.db
if RUN_ENV == "cloud":
    DB_PATH = Path("/tmp/cq.db")
else:
    DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cq.db"

# JSONL パス（必要なら）
JSONL_PATH = _get(
    "CQ_JSONL_PATH",
    str(Path(__file__).resolve().parents[2] / "data" / "questions.jsonl")
)
