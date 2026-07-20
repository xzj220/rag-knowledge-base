import os
from pathlib import Path

if os.name == "nt":
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")

LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-I75YDDQaLUcQcsPextyYiE5LSIrwPBBLPbIaJJLxh2ooknh9")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://lindaai.cn/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = os.environ.get("DB_PATH", str(DATA_DIR / "rag_users.db"))
CHROMA_PATH = os.environ.get("CHROMA_PATH", str(DATA_DIR / "rag_multi_db"))
CONV_DIR = Path(os.environ.get("CONV_DIR", str(DATA_DIR / "rag_conversations")))
