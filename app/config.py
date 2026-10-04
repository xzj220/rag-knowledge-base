import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env():
    """加载本地 .env 文件（不依赖第三方库）。
    这样敏感信息（如 API Key）只留在本地，不会提交到仓库。
    """
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

# Windows 下自动使用国内 HuggingFace 镜像，加速模型下载
if os.name == "nt" and not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ---------- 模型配置 ----------
EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://lindaai.cn/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

# ---------- 本地数据目录（默认放在项目下的 data/）----------
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = os.environ.get("DB_PATH", str(DATA_DIR / "rag_users.db"))
CHROMA_PATH = os.environ.get("CHROMA_PATH", str(DATA_DIR / "rag_multi_db"))
CONV_DIR = Path(os.environ.get("CONV_DIR", str(DATA_DIR / "rag_conversations")))
