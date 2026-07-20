from sentence_transformers import SentenceTransformer
from langchain_openai import ChatOpenAI

from .config import EMBED_MODEL_NAME, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

_model = None
def get_model():
    global _model
    if _model is None:
        print(f"Loading embedding model: {EMBED_MODEL_NAME} ...")
        _model = SentenceTransformer(EMBED_MODEL_NAME)
        print("Embedding model loaded.")
    return _model

llm = None
def get_llm():
    global llm
    if llm is None and LLM_API_KEY:
        llm = ChatOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, model=LLM_MODEL, temperature=0.3)
    return llm

try:
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_angle_cls=True, lang='ch')
except ImportError:
    ocr = None
