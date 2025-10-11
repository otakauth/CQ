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
# JSONL パス（必要なら）
JSONL_PATH = _get(
    "CQ_JSONL_PATH",
    str(Path(__file__).resolve().parents[2] / "data" / "questions.jsonl")
)

# --- Streamlit Cloud対応: 一時ディレクトリの安全利用（ローカルWindowsで警告を出さない） ---
import shutil
import tempfile
import platform
from pathlib import Path

# 既存の fallback で設定されたパス（または config 由来のパス）を尊重
_DEFAULT_DB_PATH = Path(DB_PATH) if "DB_PATH" in globals() else Path("data/cq.db")
_DEFAULT_JSONL_PATH = Path(JSONL_PATH) if "JSONL_PATH" in globals() else Path("data/questions.jsonl")

# /tmp があるPOSIX系（Streamlit Cloud含む）だけ、一時領域を優先
_TMP_DIR = Path(tempfile.gettempdir())
_IS_POSIX_TMP = (os.name == "posix") and _TMP_DIR.exists() and os.access(_TMP_DIR, os.W_OK)

# Cloud想定：DBは/tmp側に置く（なければ後で生成・コピー）
if _IS_POSIX_TMP:
    DB_PATH = _TMP_DIR / "cq.db"
else:
    DB_PATH = _DEFAULT_DB_PATH  # Windowsローカル等は data/cq.db をそのまま使う

JSONL_PATH = _DEFAULT_JSONL_PATH

# 必要なディレクトリを作成
try:
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# POSIX環境かつ /tmp 側が未作成で、ローカルdata側にDBが既にあるならコピー（静かに失敗許容）
if _IS_POSIX_TMP and (not DB_PATH.exists()) and _DEFAULT_DB_PATH.exists():
    try:
        shutil.copy(_DEFAULT_DB_PATH, DB_PATH)
        print("✅ Copied DB to temporary directory for Cloud runtime")
    except Exception as e:
        # Cloud初回などで data 側が無いこともあるため、警告だけに留める
        print(f"⚠️ Temp DB copy skipped: {e}")
