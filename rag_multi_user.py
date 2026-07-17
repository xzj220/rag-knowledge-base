import os, json, time
if os.name == "nt":
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from flask import Flask, request, jsonify, render_template_string, session
from sentence_transformers import SentenceTransformer
from langchain_community.document_loaders import TextLoader, PyPDFLoader, UnstructuredWordDocumentLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import ChatOpenAI
import chromadb, hashlib, sqlite3, tempfile, shutil
from datetime import datetime
from pathlib import Path

try:
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_angle_cls=True, lang='ch')
except ImportError:
    ocr = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "rag-secret-key-2024")
EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
_model = None
def get_model():
    global _model
    if _model is None:
        print(f"Loading embedding model: {EMBED_MODEL_NAME} ...")
        _model = SentenceTransformer(EMBED_MODEL_NAME)
        print("Embedding model loaded.")
    return _model

# Pre-load model at startup so Railway health check waits for it
get_model()

LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-I75YDDQaLUcQcsPextyYiE5LSIrwPBBLPbIaJJLxh2ooknh9")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://lindaai.cn/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

llm = None  # 棣栨浣跨敤鏃舵寜闇€鍒濆鍖?
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = os.environ.get("DB_PATH", str(DATA_DIR / "rag_users.db"))
CHROMA_PATH = os.environ.get("CHROMA_PATH", str(DATA_DIR / "rag_multi_db"))
CONV_DIR = Path(os.environ.get("CONV_DIR", str(DATA_DIR / "rag_conversations")))
CONV_DIR.mkdir(parents=True, exist_ok=True)

def init_user_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
    conn.commit(); conn.close()
init_user_db()

def register_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    pw = hashlib.sha256(password.encode()).hexdigest()
    try: conn.execute("INSERT INTO users VALUES (?, ?)", (username, pw)); conn.commit(); conn.close(); return True
    except: conn.close(); return False

def check_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    pw = hashlib.sha256(password.encode()).hexdigest()
    r = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, pw)).fetchone()
    conn.close(); return r is not None

client = chromadb.PersistentClient(path=CHROMA_PATH)

def embed(texts):
    if isinstance(texts, str): texts = [texts]
    return get_model().encode(texts).tolist()

CONV_DIR.mkdir(parents=True, exist_ok=True)

def load_convs(username):
    p = CONV_DIR / f"{username}.json"
    if not p.exists(): return []
    return json.loads(p.read_text("utf-8"))

def save_convs(username, convs):
    (CONV_DIR / f"{username}.json").write_text(json.dumps(convs, ensure_ascii=False, indent=2), "utf-8")

def get_user_collection(username):
    name = f"user_{username}"
    try: return client.get_collection(name, embedding_function=None)
    except: return client.create_collection(name, embedding_function=None)

# 每个用户的文档计数器（存在内存里，避免每次 count() 查询库）_doc_counters = {}
def next_id(username):
    col = get_user_collection(username)
    if username not in _doc_counters:
        _doc_counters[username] = col.count()
    _doc_counters[username] += 1
    return f"doc_{_doc_counters[username]}"

LOGIN_HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RAG - 登录</title><style>*{margin:0;padding:0;box-sizing:border-box}body{background:#1a1b2e;font-family:'Inter',-apple-system,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}.card{background:#22233a;border:1px solid #3d3e5c;border-radius:12px;padding:40px;width:380px}h1{text-align:center;color:#ecedf5;margin-bottom:8px;font-size:24px;font-weight:600}p{text-align:center;color:#b8b9d0;margin-bottom:24px;font-size:14px}input{width:100%;padding:12px 16px;border:1px solid #3d3e5c;border-radius:8px;font-size:14px;outline:none;margin-bottom:12px;background:#2a2b46;color:#ecedf5;transition:border-color .2s}input:focus{border-color:#818cf8}input::placeholder{color:#80819e}.btn{width:100%;padding:12px;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;background:#818cf8;color:#fff;margin-bottom:8px;transition:opacity .2s}.btn:hover{opacity:.9}.link{text-align:center;font-size:13px;color:#818cf8;cursor:pointer;margin-top:8px}.link:hover{text-decoration:underline}.err{color:#fb7185;font-size:13px;text-align:center;margin-top:8px}</style></head><body><div class="card"><h1>RAG 知识库</h1><p>登录后使用个人知识库</p><form method="POST" action="/login"><input name="username" placeholder="用户名" autocomplete="username" required><input name="password" type="password" placeholder="密码" autocomplete="current-password" required><button class="btn">登录</button></form><div class="link" onclick="location.href='/reg'">没有账号？注册</div>{% if err %}<div class="err">{{ err }}</div>{% endif %}</div></body></html>"""

REG_HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RAG - 注册</title><style>*{margin:0;padding:0;box-sizing:border-box}body{background:#1a1b2e;font-family:'Inter',-apple-system,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}.card{background:#22233a;border:1px solid #3d3e5c;border-radius:12px;padding:40px;width:380px}h1{text-align:center;color:#ecedf5;margin-bottom:8px;font-size:24px;font-weight:600}p{text-align:center;color:#b8b9d0;margin-bottom:24px;font-size:14px}input{width:100%;padding:12px 16px;border:1px solid #3d3e5c;border-radius:8px;font-size:14px;outline:none;margin-bottom:12px;background:#2a2b46;color:#ecedf5;transition:border-color .2s}input:focus{border-color:#818cf8}input::placeholder{color:#80819e}.btn{width:100%;padding:12px;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;background:#818cf8;color:#fff;margin-bottom:8px;transition:opacity .2s}.btn:hover{opacity:.9}.link{text-align:center;font-size:13px;color:#818cf8;cursor:pointer;margin-top:8px}.link:hover{text-decoration:underline}.msg{color:#34d399;font-size:13px;text-align:center;margin-top:8px}.err{color:#fb7185;font-size:13px;text-align:center;margin-top:8px}</style></head><body><div class="card"><h1>注册账号</h1><p>创建你的个人知识库</p><form method="POST" action="/register"><input name="username" placeholder="用户名" autocomplete="username" required><input name="password" type="password" placeholder="密码" autocomplete="new-password" required><button class="btn">注册</button></form><div class="link" onclick="location.href='/'">已有账号？登录</div>{% if msg %}<div class="msg">{{ msg }}</div>{% endif %}{% if err %}<div class="err">{{ err }}</div>{% endif %}</div></body></html>"""

MAIN_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAG - {{ user }}</title>
<style>
:root{--bg:#1e1e32;--bg2:#282844;--bg3:#32325a;--border:#3d3d5c;--text:#e8e8f0;--text2:#b0b0c8;--text3:#78789a;--indigo:#818cf8;--emerald:#34d399;--rose:#fb7185;--amber:#fbbf24;--radius:8px;--font:'Inter',-apple-system,sans-serif;--mono:'JetBrains Mono',monospace}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:15px;height:100vh;overflow:hidden;display:flex;flex-direction:column}
/* ===== TOP BAR ===== */
.top-bar{display:flex;align-items:center;padding:10px 16px;background:var(--bg2);border-bottom:1px solid var(--border);gap:8px;flex-shrink:0}
.top-bar h1{font-size:16px;font-weight:600;flex:1}
.top-bar .btn{background:none;border:none;color:var(--text3);cursor:pointer;padding:6px 10px;border-radius:var(--radius);font-size:18px;transition:all .15s}
.top-bar .btn:hover{color:var(--text);background:var(--bg3)}
.top-bar .logout{color:var(--text3);font-size:13px;text-decoration:none;padding:6px 12px;border-radius:var(--radius)}
.top-bar .logout:hover{color:var(--rose);background:var(--bg3)}
/* ===== TABS ===== */
.tabs{display:flex;border-bottom:1px solid var(--border);flex-shrink:0;background:var(--bg2);overflow-x:auto}
.tabs::-webkit-scrollbar{height:0}
.tab{padding:10px 20px;font-size:13px;color:var(--text3);cursor:pointer;white-space:nowrap;border-bottom:2px solid transparent;transition:all .15s}
.tab:hover{color:var(--text);background:var(--bg3)}
.tab.active{color:var(--indigo);border-bottom-color:var(--indigo)}
/* ===== CONTENT ===== */
.content{flex:1;overflow:hidden;position:relative}
.page{display:none;height:100%;overflow-y:auto;padding:16px}
.page.active{display:block}
.page::-webkit-scrollbar{width:5px}
.page::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
/* ===== CHAT ===== */
.msgs{padding:0 0 12px;min-height:100px}
.msg-wrap{display:flex;margin-bottom:14px}
.msg-wrap.user{justify-content:flex-end}
.msg-wrap.assistant{justify-content:flex-start}
.msg-bubble{max-width:80%;padding:10px 16px;border-radius:12px;line-height:1.6;word-wrap:break-word}
.msg-wrap.user .msg-bubble{background:#312e81;border-bottom-right-radius:4px}
.msg-wrap.assistant .msg-bubble{background:var(--bg3);border-bottom-left-radius:4px}
.msg-footer{font-size:11px;color:var(--text3);margin-top:4px;display:flex;gap:10px;flex-wrap:wrap}
.ref-sup{color:var(--indigo);cursor:pointer;font-size:11px;font-weight:600;text-decoration:none;border-bottom:1px dotted var(--indigo)}
.ref-sup:hover{color:var(--emerald)}
.ref-tooltip{display:none;position:fixed;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;max-width:380px;font-size:13px;z-index:100;color:var(--text2)}
.ref-tooltip.show{display:block}
.code-block{margin:8px 0;border-radius:var(--radius);overflow:hidden;border:1px solid var(--border)}
.code-title{display:flex;align-items:center;gap:5px;padding:6px 12px;background:var(--bg);border-bottom:1px solid var(--border)}
.code-title .dot{width:8px;height:8px;border-radius:50%}
.code-title .dot.r{background:#ff5f57}
.code-title .dot.y{background:#ffbd2e}
.code-title .dot.g{background:#28c840}
.code-title .lang{font-size:11px;color:var(--text3);margin-left:auto;font-family:var(--mono)}
.code-title .copy-btn{background:none;border:none;color:var(--text3);cursor:pointer;font-size:11px;padding:2px 6px;border-radius:4px}
.code-title .copy-btn:hover{color:var(--text);background:var(--bg3)}
.code-block pre{margin:0;padding:10px 14px;background:var(--bg2);overflow-x:auto;font-family:var(--mono);font-size:13px;color:var(--text2)}
/* ===== INPUT ===== */
.input-row{display:flex;gap:8px;align-items:flex-end;padding:12px 0 0;border-top:1px solid var(--border);margin-top:8px}
.input-row textarea{flex:1;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;color:var(--text);font-family:var(--font);font-size:14px;outline:none;resize:none;max-height:120px;line-height:1.5}
.input-row textarea:focus{border-color:var(--indigo)}
.input-row textarea::placeholder{color:var(--text3)}
.input-row .send-btn{width:40px;height:40px;border:none;border-radius:var(--radius);background:var(--indigo);color:#fff;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.input-row .send-btn:hover{opacity:.85}
.input-row .send-btn:disabled{opacity:.4}
.progress-bar{height:2px;background:var(--bg3);border-radius:1px;overflow:hidden;opacity:0;transition:opacity .2s}
.progress-bar.active{opacity:1}
.progress-bar .fill{height:100%;width:0;background:linear-gradient(90deg,var(--indigo),var(--emerald));animation:progress 1.5s ease-in-out infinite}
@keyframes progress{0%{width:0}50%{width:70%}100%{width:100%}}
.shortcuts{font-size:11px;color:var(--text3);margin-top:4px}
/* ===== CONV OVERLAY ===== */
.conv-overlay{display:none;position:fixed;top:0;right:0;bottom:0;width:360px;background:var(--bg2);border-left:1px solid var(--border);z-index:26;flex-direction:column}
.conv-overlay.show{display:flex}
@media(max-width:900px){.conv-overlay{width:300px}}
@media(max-width:700px){.conv-overlay{width:100%;z-index:36}}
.main.pnl-closed:not(.conv-open){margin-right:0}
.conv-overlay .co-header{display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid var(--border);flex-shrink:0;gap:8px}
.conv-overlay .co-header h3{font-size:15px;font-weight:600;flex:1}
.conv-overlay .co-header .back-btn{background:none;border:none;color:var(--text3);cursor:pointer;font-size:18px;padding:6px 10px;border-radius:4px}
.conv-overlay .co-header .back-btn:hover{color:var(--text);background:var(--bg3)}
.conv-list{flex:1;overflow-y:auto;padding:4px 0}
.conv-empty{padding:40px 16px;text-align:center;color:var(--text3)}
.conv-folder{border-bottom:1px solid var(--border)}
.conv-folder-head{display:flex;align-items:center;padding:10px 14px;cursor:pointer;gap:8px;transition:background .15s}
.conv-folder-head:hover{background:var(--bg3)}
.folder-icon{font-size:10px;color:var(--text3);width:14px;flex-shrink:0}
.folder-label{font-size:13px;font-weight:500;color:var(--text)}
.folder-count{font-size:11px;color:var(--text3);margin-left:auto}
.conv-folder-body{display:none;padding:0 0 4px 14px}
.conv-folder-body.open{display:block}
.conv-item{display:flex;align-items:center;padding:6px 12px 6px 20px;cursor:pointer;border-left:2px solid transparent;gap:6px;border-radius:0 6px 6px 0;margin:1px 0}
.conv-item:hover{background:var(--bg3)}
.conv-item.active{border-left-color:var(--indigo);background:var(--bg3)}
.conv-item .conv-time{font-size:11px;color:var(--text3);flex-shrink:0;width:36px}
.conv-item .conv-title{flex:1;padding:0;color:var(--text2);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.conv-item .conv-del{background:none;border:none;color:transparent;cursor:pointer;font-size:12px;padding:2px 6px;border-radius:4px;flex-shrink:0}
.conv-item:hover .conv-del{color:var(--text3)}
.conv-item .conv-del:hover{color:var(--rose)!important}
/* ===== TOAST ===== */
.toast{position:fixed;top:16px;left:50%;transform:translateX(-50%);padding:8px 20px;border-radius:var(--radius);font-size:13px;z-index:999;opacity:0;transition:opacity .3s;pointer-events:none}
.toast.show{opacity:1}
.toast.ok{background:#064e3b;border:1px solid var(--emerald);color:var(--emerald)}
.toast.err{background:#4c0519;border:1px solid var(--rose);color:var(--rose)}
.toast.info{background:var(--bg3);border:1px solid var(--border);color:var(--text2)}
/* ===== BUTTONS ===== */
.btn{padding:8px 16px;border:none;border-radius:var(--radius);font-size:13px;font-weight:500;cursor:pointer;display:inline-flex;align-items:center;gap:4px;transition:opacity .2s}
.btn-primary{background:var(--indigo);color:#fff}
.btn-primary:hover{opacity:.85}
.btn-sm{padding:5px 10px;font-size:12px}
.btn-rose{background:var(--rose);color:#fff}
/* ===== KNOWLEDGE BASE ===== */
.kb-header{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.kb-header input{flex:1;min-width:120px;padding:8px 12px;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-size:13px;outline:none}
.kb-header input:focus{border-color:var(--indigo)}
.kb-header input::placeholder{color:var(--text3)}
.kb-toolbar{display:flex;align-items:center;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.kb-toolbar label{font-size:12px;color:var(--text3);cursor:pointer;display:flex;align-items:center;gap:4px}
.doc-group{border:1px solid var(--border);border-radius:var(--radius);margin-bottom:8px;overflow:hidden}
.doc-group .dg-head{display:flex;align-items:center;gap:6px;padding:8px 12px;cursor:pointer;transition:background .15s}
.doc-group .dg-head:hover{background:var(--bg3)}
.doc-group .dg-head .dg-name{flex:1;font-size:13px;font-weight:500}
.doc-group .dg-head .dg-meta{font-size:11px;color:var(--text3)}
.doc-chunks{display:none;border-top:1px solid var(--border);padding:6px 12px 6px 36px}
.doc-chunks.open{display:block}
.chunk-item{padding:5px 0;font-size:12px;color:var(--text2);border-bottom:1px dashed var(--border)}
.chunk-item:last-child{border-bottom:none}
.chunk-item label{display:flex;align-items:flex-start;gap:4px;cursor:pointer}
.drop-zone{border:2px dashed var(--border);border-radius:var(--radius);padding:24px;text-align:center;cursor:pointer;transition:all .2s;background:var(--bg2);margin-bottom:10px}
.drop-zone:hover{border-color:var(--indigo);background:var(--indigo-bg)}
.drop-zone.dragover{border-color:var(--indigo);background:var(--indigo-bg)}
.drop-zone p{color:var(--text3);font-size:13px}
/* ===== MANUAL INPUT ===== */
.manual-box textarea{width:100%;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:10px 12px;color:var(--text);font-family:var(--mono);font-size:13px;outline:none;resize:vertical;min-height:100px}
.manual-box textarea:focus{border-color:var(--indigo)}
.manual-box textarea::placeholder{color:var(--text3)}
/* ===== SIDEBAR NAV ===== */
.nav{position:fixed;left:0;top:0;bottom:0;width:48px;background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;align-items:center;padding:8px 0;z-index:30;overflow:hidden;transition:width .2s}
.nav.expand{width:180px}
.nav .nav-toggle{cursor:pointer;background:none;border:none;color:var(--text3);font-size:16px;padding:6px;margin-bottom:8px;border-radius:4px;flex-shrink:0}
.nav .nav-toggle:hover{color:var(--text);background:var(--bg3)}
.nav .nav-item{display:flex;align-items:center;gap:6px;width:100%;padding:10px 14px;cursor:pointer;color:var(--text3);font-size:13px;white-space:nowrap;border-left:2px solid transparent;transition:all .15s;flex-shrink:0}
.nav .nav-item:hover{color:var(--text);background:var(--bg3)}
.nav .nav-item.active{border-left-color:var(--indigo);color:var(--indigo);background:var(--bg3)}
.nav .nav-item .ico{font-size:16px;width:20px;text-align:center;flex-shrink:0}
.nav .nav-item .lab{display:none}
.nav.expand .nav-item .lab{display:inline}
.nav .nav-spacer{flex:1}
.nav .user{font-size:11px;color:var(--text3);padding:4px 0;display:none;white-space:nowrap}
.nav.expand .user{display:block}
.nav .logout-btn{font-size:11px;color:var(--text3);cursor:pointer;padding:6px 14px;display:none;white-space:nowrap}
.nav.expand .logout-btn{display:block}
.nav .logout-btn:hover{color:var(--rose)}
/* ===== MOBILE OVERLAY ===== */
.mob-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:29}
.mob-overlay.show{display:block}
/* ===== MOBILE TOP BAR ===== */
.mob-top{display:none;align-items:center;padding:8px 12px;background:var(--bg2);border-bottom:1px solid var(--border);gap:8px;flex-shrink:0}
.mob-top h2{font-size:16px;font-weight:600;flex:1}
.mob-top .hamburger{background:none;border:none;color:var(--text);font-size:20px;cursor:pointer;padding:4px 8px}
.mob-top .btn-ico{background:none;border:none;color:var(--text3);font-size:18px;cursor:pointer;padding:4px 8px;border-radius:4px}
.mob-top .btn-ico:hover{color:var(--text);background:var(--bg3)}
/* ===== MAIN LAYOUT ===== */
.main{height:100vh;display:flex;flex-direction:column;transition:margin .25s}
.nav ~ .main{margin-left:48px;margin-right:360px}
.nav.expand ~ .main{margin-left:180px}
.main.pnl-closed{margin-right:0}
.main .chat-header{display:flex;align-items:center;padding:10px 16px;border-bottom:1px solid var(--border);flex-shrink:0;gap:6px}
.main .chat-header h2{font-size:15px;font-weight:600;flex:1}
.main .chat-header .btn-ico{background:none;border:none;color:var(--text3);font-size:16px;cursor:pointer;padding:4px 8px;border-radius:4px}
.main .chat-header .btn-ico:hover{color:var(--text);background:var(--bg3)}
.msgs{flex:1;overflow-y:auto;padding:16px}
.input-area{padding:12px 16px;border-top:1px solid var(--border);background:var(--bg);flex-shrink:0}
.input-row .new-chat-btn{display:none;width:36px;height:36px;border:none;border-radius:var(--radius);background:var(--bg3);color:var(--text);cursor:pointer;font-size:16px;flex-shrink:0}
.shortcuts-hint{font-size:11px;color:var(--text3);margin-top:6px;text-align:center}
/* ===== RIGHT PANEL ===== */
.panel-wrap{position:fixed;right:0;top:0;bottom:0;width:360px;background:var(--bg2);border-left:1px solid var(--border);z-index:25;display:flex;flex-direction:column;transition:transform .25s}
.panel-wrap:not(.open){transform:translateX(100%)}
.panel{flex:1;display:flex;flex-direction:column;overflow:hidden}
.panel-header{display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid var(--border);flex-shrink:0}
.panel-header h3{font-size:14px;font-weight:600;flex:1}
.panel-header .close-btn{background:none;border:none;color:var(--text3);font-size:16px;cursor:pointer;padding:4px 8px;border-radius:4px}
.panel-header .close-btn:hover{color:var(--text);background:var(--bg3)}
.panel-search{padding:8px 12px;flex-shrink:0}
.panel-search input{width:100%;padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-size:13px;outline:none}
.panel-search input:focus{border-color:var(--indigo)}
.panel-search input::placeholder{color:var(--text3)}
.panel-body{flex:1;overflow-y:auto;padding:0}
.panel-body::-webkit-scrollbar{width:4px}
.panel-body::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
.panel-empty{padding:40px 16px;text-align:center;color:var(--text3);font-size:13px}
.panel-section{padding:12px}
.panel-section textarea{width:100%;min-height:120px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:10px 12px;color:var(--text);font-size:13px;outline:none;resize:vertical}
.panel-section textarea:focus{border-color:var(--indigo)}
.panel-section .btn-sm{padding:6px 14px;border:none;border-radius:var(--radius);font-size:12px;cursor:pointer;margin-top:8px}
.panel-section .btn-indigo{background:var(--indigo);color:#fff}
.panel-section .btn-indigo:hover{opacity:.85}
.drop-zone{padding:16px;text-align:center;border:2px dashed var(--border);border-radius:var(--radius);cursor:pointer;background:var(--bg);margin:12px;flex-shrink:0;transition:border-color .2s,background .2s}
.drop-zone:hover{border-color:var(--indigo);background:var(--bg3)}
.drop-zone.dragover{border-color:var(--indigo);background:var(--bg3)}
.drop-zone .big{font-size:28px;color:var(--text3);margin-bottom:4px}
.drop-zone p{font-size:12px;color:var(--text3)}
.upload-progress{display:none;padding:8px 12px;font-size:12px;color:var(--text2);flex-shrink:0}
/* ===== RESPONSIVE ===== */
@media(max-width:900px){
  .panel-wrap{width:300px}
  .conv-overlay{width:300px}
  .nav ~ .main{margin-right:300px}
  .main.pnl-closed:not(.conv-open){margin-right:0}
}
@media(max-width:700px){
  .nav{display:none}
  .nav.expand{width:48px}
  .nav ~ .main,.nav.expand ~ .main{margin-left:0;margin-right:0}
  .mob-top{display:flex}
  .panel-wrap{width:100%;z-index:35}
  .nav.mob-show{display:flex;width:240px;z-index:40}
  .main .chat-header .btn-ico{display:none}
  .main .chat-header .btn-ico:last-child{display:inline-flex}
  .input-row .new-chat-btn{display:flex}
  .shortcuts-hint{font-size:10px}
}
/* ===== DOC ITEMS (KB) ===== */
.doc-item{border-bottom:1px solid var(--border);padding:6px 12px}
.doc-name{display:flex;align-items:center;gap:6px;font-size:13px;font-weight:500;cursor:pointer}
.doc-name .icon{font-size:14px}
.doc-meta{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text3);margin-top:2px;padding-left:22px}
.tag{font-size:10px;padding:1px 6px;border-radius:3px}
.tag-indexed{background:rgba(52,211,153,.15);color:var(--emerald)}
.doc-chunks{display:none;padding:4px 0 4px 22px}
.doc-chunks.open{display:block}
.chunk-item{padding:3px 0;font-size:12px;color:var(--text2);border-bottom:1px dashed var(--border)}
.chunk-item:last-child{border-bottom:none}
</style>
</head>
<body>

<div class="mob-overlay" id="mobOverlay" onclick="closeMobNav()"></div>
<div class="nav" id="navBar">
  <button class="nav-toggle" onclick="toggleNav()" title="折叠/展开侧栏">☰</button>
  <div class="nav-item active" data-tab="chat" onclick="switchNav('chat');closeMobNav()">
    <span class="ico">💬</span><span class="lab">对话</span>
  </div>
  <div class="nav-item" data-tab="kb" onclick="switchNav('kb');closeMobNav()">
    <span class="ico">📚</span><span class="lab">知识库</span>
  </div>
  <div class="nav-item" data-tab="add" onclick="switchNav('add');closeMobNav()">
    <span class="ico">✏️</span><span class="lab">手动录入</span>
  </div>
  <div class="nav-item" onclick="showConvList();closeMobNav()" style="cursor:pointer">
    <span class="ico">📜</span><span class="lab">历史对话</span>
  </div>
  <div class="nav-item" onclick="newChat();closeMobNav()" style="cursor:pointer">
    <span class="ico">✚</span><span class="lab">新对话</span>
  </div>
  <div class="nav-spacer"></div>
  <div class="user">{{ user }}</div>
  <div class="logout-btn" onclick="location.href='/logout'">退出登录</div>
</div>
<div class="mob-top">
  <button class="hamburger" onclick="openMobNav()">☰</button>
  <h2>RAG</h2>
  <button class="btn-ico" onclick="togglePanel()" title="知识库">📋</button>
</div>

<!-- ===== MAIN CHAT ===== -->
<div class="main" id="mainArea">
  <div class="chat-header">
    <h2>对话</h2>
    <button class="btn-ico" onclick="showConvList()" title="历史对话">📜</button>
    <button class="btn-ico" onclick="togglePanel()" title="知识库面板 (Ctrl+B)">📋</button>
    <button class="btn-ico" onclick="newChat()" title="新建对话 (Ctrl+L)">✚</button>
  </div>
  <div class="msgs" id="msgList"></div>
  <div class="input-area">
    <div class="progress-bar" id="progressBar"><div class="fill"></div></div>
    <div class="input-row">
      <button class="new-chat-btn" id="mobileNewChat" onclick="newChat()" title="新对话" style="display:none">✚</button>
      <textarea id="chatInput" rows="1" placeholder="输入问题… (Shift+Enter 换行, Enter 发送)" onkeydown="onInputKey(event)" oninput="autoResize(this)"></textarea>
      <button class="send-btn" id="sendBtn" onclick="sendMsg()">➤</button>
    </div>
    <div class="shortcuts-hint">Ctrl+K 聚焦 · Ctrl+B 面板 · Ctrl+L 新对话 · 📜 历史对话</div>
  </div>
</div>

<!-- ===== CONVERSATION OVERLAY ===== -->
<div class="conv-overlay" id="convOverlay" onclick="if(event.target===this)hideConvList()">
  <div class="co-header" onclick="event.stopPropagation()">
    <button class="back-btn" onclick="hideConvList()">←</button>
    <h3>历史对话</h3>
    <span id="convTotal" style="font-size:12px;color:var(--text3)"></span>
  </div>
  <div class="conv-list" id="convList" onclick="event.stopPropagation()"></div>
</div>

<!-- ===== RIGHT PANEL ===== -->
<div class="panel-wrap open" id="panelWrap">
  <div class="panel">
    <div class="panel-header">
      <h3>知识库</h3>
      <button class="close-btn" onclick="togglePanel()">✕</button>
    </div>
    <div class="panel-search">
      <input id="kbSearch" placeholder="搜索知识库…" oninput="filterDocs()">
    </div>
    <div class="panel-body" id="kbBody">
      <div class="panel-empty">加载中…</div>
    </div>
    <div class="drop-zone" id="kbDrop" onclick="document.getElementById('kbFile').click()">
      <div class="big">+</div>
      <p>拖拽或点击上传文件</p>
      <p style="font-size:11px;color:var(--text3);margin-top:4px">PDF / Word / TXT / 图片 (自动OCR)</p>
    </div>
    <input type="file" id="kbFile" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.bmp" style="display:none" onchange="uploadDoc(this.files[0])">
    <div class="upload-progress" id="uploadProgress"></div>
  </div>
</div>

<!-- ===== TOAST ===== -->
<div class="toast" id="toast"></div>

<!-- ===== REF TOOLTIP ===== -->
<div class="ref-tooltip" id="refTooltip"></div>

<script>
// ===== STATE =====
let convs = []; let curConvId = null; let msgs = []; let isSending = false;

// ===== NAV =====
function switchNav(tab) {
  hideConvList()
  document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.tab === tab))
  if (tab === 'kb') { togglePanel(true); loadDocs() }
  if (tab === 'add') { togglePanel(true); showAddPanel() }
}

// ===== NAV TOGGLE =====
function toggleNav() {
  document.getElementById('navBar').classList.toggle('expand')
}
function openMobNav() {
  document.getElementById('navBar').classList.add('mob-show')
  document.getElementById('mobOverlay').classList.add('show')
}
function closeMobNav() {
  document.getElementById('navBar').classList.remove('mob-show')
  document.getElementById('mobOverlay').classList.remove('show')
}

// ===== PANEL =====
function togglePanel(force) {
  const w = document.getElementById('panelWrap')
  const m = document.getElementById('mainArea')
  const o = w.classList.contains('open')
  if (force === true) { w.classList.add('open'); m.classList.remove('pnl-closed') }
  else if (force === false) { w.classList.remove('open'); m.classList.add('pnl-closed') }
  else { w.classList.toggle('open'); m.classList.toggle('pnl-closed') }
}

// ===== TOAST =====
function toast(msg, type = 'info', duration = 3000) {
  const el = document.getElementById('toast'); el.textContent = msg;
  el.className = 'toast ' + type + ' show';
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove('show'), duration)
}

// ===== SEND =====
function onInputKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg() }
}

function autoResize(el) {
  el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

function sendMsg() {
  const inp = document.getElementById('chatInput'); const q = inp.value.trim()
  if (!q || isSending) return
  inp.value = ''; inp.style.height = 'auto'
  addMsg('user', q)

  const bar = document.getElementById('progressBar'); bar.classList.add('active')
  const btn = document.getElementById('sendBtn'); btn.disabled = true; isSending = true

  const startT = Date.now()
  fetch('/ask', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q:q})})
    .then(r => r.json()).then(d => {
      bar.classList.remove('active')
      if (d.answer) {
        addMsg('assistant', formatAnswer(d.answer, d.sources || []), d)
        saveConv()
      } else {
        addMsg('assistant', '<p>未找到相关材料</p>')
      }
    }).catch(() => {
      bar.classList.remove('active')
      toast('请求失败，请重试', 'err')
    }).finally(() => { btn.disabled = false; isSending = false })
}

function addMsg(role, html, extra) {
  const list = document.getElementById('msgList')
  const wrap = document.createElement('div')
  wrap.className = 'msg-wrap ' + role
  const t = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'})
  let foot = ''
  if (extra && role === 'assistant') {
    const ti = extra.timing || {}
    const tk = extra.tokens || {}
    foot = `<div class="msg-footer"><span>⏱ 检索 ${ti.retrieval||'?'}s</span><span>🧠 ${ti.thinking||'?'}s</span>${tk.input?`<span>📥 ${tk.input}</span><span>📤 ${tk.output}</span>`:''}${extra.sources?`<span>📎 ${extra.sources.length} 个来源</span>`:''}</div>`
  }
  wrap.innerHTML = `<div class="msg-bubble">${html}${foot}</div><div class="time">${t}</div>`
  list.appendChild(wrap)
  scrollBottom()
  msgs.push({role, html, extra})
}

function scrollBottom() {
  const list = document.getElementById('msgList')
  // Only scroll if user is near bottom
  const threshold = 80
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight <= threshold
  if (atBottom) list.scrollTop = list.scrollHeight
}

function formatAnswer(text, sources) {
  // Replace [N] with clickable superscript
  let html = text.replace(/\[(\d+)\]/g, (m, n) => {
    const idx = parseInt(n) - 1
    if (sources && sources[idx]) {
      return `<a class="ref-sup" href="#" data-idx="${idx}" onclick="showRef(this,${idx});return false">[${n}]</a>`
    }
    return m
  })
  // Wrap code blocks
    html = html.replace(/```(\w*)\\n([\s\S]*?)```/g, (m, lang, code) => {
    const id = 'cb' + Date.now() + Math.random().toString(36).slice(2,6)
    return `<div class="code-block"><div class="code-title"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span><span class="lang">${lang||'code'}</span><button class="copy-btn" onclick="copyCode(this,'${id}')">复制</button></div><pre id="${id}">${escHtml(code.trim())}</pre></div>`
  })
  html = html.replace(/\\n/g, '<br>')
  return html
}

function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') }

// ===== SOURCE TOOLTIP =====
function showRef(el, idx) {
  const tip = document.getElementById('refTooltip')
  // Get source text from last response
  const last = msgs.filter(m => m.role === 'assistant').pop()
  if (last && last.extra && last.extra.sources && last.extra.sources[idx]) {
    tip.textContent = last.extra.sources[idx].text
  } else {
    tip.textContent = '来源内容不可用'
  }
  const rect = el.getBoundingClientRect()
  tip.style.left = Math.min(rect.left, window.innerWidth - 420) + 'px'
  tip.style.top = (rect.bottom + 6) + 'px'
  tip.classList.add('show')
  document.addEventListener('click', closeRef, {once:true})
}
function closeRef() { document.getElementById('refTooltip').classList.remove('show') }

// ===== COPY CODE =====
function copyCode(btn, id) {
  const text = document.getElementById(id).textContent
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent; btn.textContent = '✓ 已复制';
    setTimeout(() => btn.textContent = orig, 1500)
  })
}

// ===== NEW CHAT =====
function newChat() {
  curConvId = null; msgs = []
  document.getElementById('msgList').innerHTML = ''
  const inp = document.getElementById('chatInput'); inp.value = ''; inp.style.height = 'auto'
  loadConvList()
}

// ===== CONVERSATIONS =====
function loadConvList() {
  return fetch('/conversations').then(r => r.json()).then(d => {
    convs = d; renderConvList()
  }).catch(() => {})
}

function showConvList() {
  document.getElementById('convOverlay').classList.add('show')
  document.getElementById('mainArea').classList.add('conv-open')
  renderConvList()
}

function hideConvList() {
  document.getElementById('convOverlay').classList.remove('show')
  document.getElementById('mainArea').classList.remove('conv-open')
}

function toggleFolder(el) {
  const body = el.nextElementSibling
  const icon = el.querySelector('.folder-icon')
  body.classList.toggle('open')
  icon.textContent = body.classList.contains('open') ? '▼' : '▶'
}

function renderConvList() {
  const el = document.getElementById('convList')
  document.getElementById('convTotal').textContent = convs.length ? convs.length + ' 条' : ''
  if (convs.length === 0) {
    el.innerHTML = '<div class="conv-empty">暂无历史对话</div>'
    return
  }
  // Group by date (e.g. "2024年7月17日 星期三")
  const groups = {}
  convs.forEach(c => {
    const d = new Date(c.updated_at || c.created_at)
    const wk = ['日','一','二','三','四','五','六'][d.getDay()]
    const key = d.getFullYear() + '年' + (d.getMonth()+1) + '月' + d.getDate() + '日 星期' + wk
    if (!groups[key]) groups[key] = []
    groups[key].push(c)
  })
  // Sort dates descending
  const sorted = Object.keys(groups).sort((a, b) => new Date(b.replace('年','/').replace('月','/').replace('日','')) - new Date(a.replace('年','/').replace('月','/').replace('日','')))
  let html = ''
  sorted.forEach(dateKey => {
    const items = groups[dateKey]
    html += `<div class="conv-folder"><div class="conv-folder-head" onclick="toggleFolder(this)"><span class="folder-icon">▶</span><span class="folder-label">${dateKey}</span><span class="folder-count">${items.length} 条</span></div><div class="conv-folder-body">`
    items.forEach(c => {
      const active = c.id === curConvId ? ' active' : ''
      const firstMsg = (c.messages && c.messages.length) ? c.messages[0].html.replace(/<[^>]*>/g,'').slice(0,28) : (c.title || '新对话')
      const d = new Date(c.updated_at || c.created_at)
      const ts = d.toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'})
      html += `<div class="conv-item${active}" onclick="loadConversation('${c.id}')"><span class="conv-time">${ts}</span><span class="conv-title">${escHtml(firstMsg)}</span><button class="conv-del" onclick="event.stopPropagation();deleteConversation('${c.id}')" title="删除">✕</button></div>`
    })
    html += '</div></div>'
  })
  el.innerHTML = html
  // Auto-open first folder
  const first = el.querySelector('.conv-folder-body')
  if (first) { first.classList.add('open'); el.querySelector('.folder-icon').textContent = '▼' }
}

function loadConversation(id) {
  const conv = convs.find(c => c.id === id)
  if (!conv) return
  curConvId = id
  msgs = conv.messages || []
  const list = document.getElementById('msgList')
  list.innerHTML = ''
  msgs.forEach(m => {
    const wrap = document.createElement('div')
    wrap.className = 'msg-wrap ' + m.role
    const t = ''
    let foot = ''
    if (m.extra && m.role === 'assistant') {
      const ti = m.extra.timing || {}; const tk = m.extra.tokens || {}
      foot = `<div class="msg-footer"><span>⏱ 检索 ${ti.retrieval||'?'}s</span><span>🧠 ${ti.thinking||'?'}s</span>${tk.input?`<span>📥 ${tk.input}</span><span>📤 ${tk.output}</span>`:''}${m.extra.sources?`<span>📎 ${m.extra.sources.length} 个来源</span>`:''}</div>`
    }
    wrap.innerHTML = `<div class="msg-bubble">${m.html}${foot}</div>`
    list.appendChild(wrap)
  })
  hideConvList()
  scrollBottom()
}

function deleteConversation(id) {
  if (!confirm('确认删除此对话？')) return
  fetch('/conversations/' + id, {method:'DELETE'}).then(r => r.json()).then(d => {
    if (d.ok) {
      if (curConvId === id) { curConvId = null; msgs = []; document.getElementById('msgList').innerHTML = '' }
      convs = convs.filter(c => c.id !== id)
      renderConvList()
      toast('已删除', 'ok')
    }
  }).catch(() => toast('删除失败', 'err'))
}

function saveConv() {
  if (msgs.length === 0) return
  const title = msgs[0].html.replace(/<[^>]*>/g,'').slice(0,40)
  const data = {id: curConvId, title, messages: msgs, updated_at: new Date().toISOString()}
  fetch('/conversations', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
    .then(r => r.json()).then(d => { curConvId = d.id; loadConvList() }).catch(() => {})
}

// ===== KNOWLEDGE BASE =====
const _kbItems = []

function loadDocs() {
  const body = document.getElementById('kbBody')
  body.innerHTML = '<div class="panel-empty">加载中…</div>'
  const q = document.getElementById('kbSearch').value.trim().toLowerCase()
  fetch('/kb_docs').then(r => r.json()).then(d => {
    _kbItems.length = 0
    let items = d.docs
    if (q) items = items.filter(x => x.text.toLowerCase().includes(q))
    _kbItems.push(...items)
    renderDocs(body, items)
  }).catch(() => { body.innerHTML = '<div class="panel-empty">加载失败</div>' })
}

function renderDocs(body, items) {
  if (items.length === 0) { body.innerHTML = '<div class="panel-empty">暂无数据</div>'; return }
  const groups = {}; let total = 0
  items.forEach(item => {
    const src = item.source || 'unknown'; total++
    if (!groups[src]) groups[src] = []
    groups[src].push(item)
  })
  const order = Object.keys(groups).sort()
  let html = ''
  // Toolbar
  html += '<div style="display:flex;align-items:center;gap:6px;padding:4px 12px 8px;border-bottom:1px solid var(--border2);flex-shrink:0">'
  html += '<label style="display:flex;align-items:center;gap:4px;font-size:12px;color:var(--text3);cursor:pointer"><input type="checkbox" id="kbSelAll" onchange="kbToggleAll()"> 全选</label>'
  html += '<button style="padding:3px 10px;border:none;border-radius:4px;background:var(--rose);color:#fff;font-size:11px;cursor:pointer" onclick="kbBatchDelete()">删除选中 (<span id="kbSelCount">0</span>)</button>'
  html += '<span style="font-size:11px;color:var(--text3);margin-left:auto">共 ' + total + ' 条</span>'
  html += '</div>'
  // Doc groups
  order.forEach(src => {
    const chunks = groups[src]
    const gid = 'g' + Date.now() + Math.random().toString(36).slice(2,6)
    html += `<div class="doc-item" data-gid="${gid}">`
    html += `<div class="doc-name"><label style="display:flex;align-items:center;gap:4px;cursor:pointer;flex:1" onclick="event.stopPropagation()"><input type="checkbox" class="kb-grp-cb" data-gid="${gid}" onchange="kbUpdCount()"> <span class="icon">${src === 'manual' ? '📝' : '📄'}</span>${escHtml(src)}</label></div>`
    html += `<div class="doc-meta"><span>${chunks.length} 片段</span><span class="tag tag-indexed">已索引</span><span style="margin-left:auto;color:var(--text3);font-size:11px;cursor:pointer" onclick="kbToggleChunks(this,'${gid}')">展开/收起</span></div>`
    html += `<div class="doc-chunks open" id="${gid}">`
    chunks.forEach((ch, i) => {
      let txt = ch.text; if (txt.length > 100) txt = txt.slice(0,100) + '…'
      html += `<div class="chunk-item" style="display:flex;align-items:flex-start;gap:4px"><input type="checkbox" class="kb-chk" data-idx="${ch.idx}" onchange="kbUpdCount()" style="margin-top:3px"> <span>${i+1}. ${escHtml(txt)}</span></div>`
    })
    html += '</div></div>'
  })
  body.innerHTML = html
}

function kbToggleAll() {
  const c = document.getElementById('kbSelAll').checked
  document.querySelectorAll('.kb-chk,.kb-grp-cb').forEach(e => e.checked = c)
  kbUpdCount()
}

function kbUpdCount() {
  const n = document.querySelectorAll('.kb-chk:checked').length
  const el = document.getElementById('kbSelCount')
  if (el) el.textContent = n
  // Update group checkboxes
  document.querySelectorAll('.doc-item').forEach(g => {
    const gid = g.dataset.gid
    if (!gid) return
    const chks = g.querySelectorAll('.kb-chk')
    const grp = g.querySelector('.kb-grp-cb')
    if (grp && chks.length) grp.checked = [...chks].every(c => c.checked)
  })
}

function kbToggleChunks(el, gid) {
  const c = document.getElementById(gid)
  if (c) c.classList.toggle('open')
}

function kbBatchDelete() {
  const sel = [...document.querySelectorAll('.kb-chk:checked')].map(c => parseInt(c.dataset.idx))
  if (sel.length === 0) { toast('请选择要删除的条目', 'err'); return }
  if (!confirm('确认删除选中的 ' + sel.length + ' 条知识？')) return
  fetch('/batch_delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({indices: sel})})
    .then(r => r.json()).then(d => {
      toast('已删除 ' + sel.length + ' 条', 'ok')
      loadDocs()
    }).catch(() => toast('删除失败', 'err'))
}

function filterDocs() { loadDocs() }

// ===== UPLOAD =====
document.getElementById('kbDrop').addEventListener('dragover', function(e){
  e.preventDefault(); this.classList.add('dragover')
})
document.getElementById('kbDrop').addEventListener('dragleave', function(){
  this.classList.remove('dragover')
})
document.getElementById('kbDrop').addEventListener('drop', function(e){
  e.preventDefault(); this.classList.remove('dragover')
  const f = e.dataTransfer.files[0]; if (f) uploadDoc(f)
})

function uploadDoc(file) {
  if (!file) return
  const ext = file.name.split('.').pop().toLowerCase()
  if (!['pdf','docx','txt','png','jpg','jpeg','bmp'].includes(ext)) { toast('不支持的文件格式', 'err'); return }
  const prog = document.getElementById('uploadProgress')
  prog.style.display = 'block'; prog.innerHTML = '⏳ 上传处理中 <b>' + escHtml(file.name) + '</b>…'
  const fd = new FormData(); fd.append('file', file)
  fetch('/upload', {method:'POST', body:fd})
    .then(r => r.json()).then(d => {
      prog.style.display = 'none'
      if (d.ok) { toast(d.msg, 'ok'); loadDocs(); document.getElementById('kbFile').value = '' }
      else toast(d.msg, 'err')
    }).catch(() => { prog.style.display = 'none'; toast('上传失败', 'err') })
}

function showAddPanel() {
  const body = document.getElementById('kbBody')
  body.innerHTML = `<div class="panel-section"><textarea id="manualInput" placeholder="每行一条：&#10;张三的电话是138xxxx&#10;李四的邮箱是admin@xx.com"></textarea><button class="btn-sm btn-indigo" onclick="manualAdd()">全部存入</button><div style="margin-top:8px;font-size:11px;color:var(--text3)">格式: 问题+是+答案</div></div>`
}

function manualAdd() {
  const t = document.getElementById('manualInput').value.trim()
  if (!t) { toast('请输入数据', 'err'); return }
  fetch('/add_batch', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text:t})})
    .then(r => r.json()).then(d => { toast(d.msg, 'ok'); document.getElementById('manualInput').value = ''; loadDocs() })
    .catch(() => toast('出错了', 'err'))
}

// ===== KEYBOARD SHORTCUTS =====
document.addEventListener('keydown', function(e) {
  if (e.ctrlKey && e.key === 'k') { e.preventDefault(); document.getElementById('chatInput').focus() }
  if (e.ctrlKey && e.key === 'b') { e.preventDefault(); togglePanel() }
  if (e.ctrlKey && e.key === 'l') { e.preventDefault(); newChat() }
})

// ===== INIT =====
loadConvList()
document.getElementById('chatInput').focus()
</script>
</body></html>"""

@app.route("/")
def index():
    if "user" in session:
        return render_template_string(MAIN_HTML, user=session["user"])
    return render_template_string(LOGIN_HTML, err="")

@app.route("/login", methods=["POST"])
def login():
    u, p = request.form["username"], request.form["password"]
    if check_user(u, p):
        session["user"] = u; get_user_collection(u)
        return render_template_string(MAIN_HTML, user=u)
    return render_template_string(LOGIN_HTML, err="用户名或密码错误")

@app.route("/reg")
def reg_page():
    return render_template_string(REG_HTML, msg="", err="")

@app.route("/register", methods=["POST"])
def register():
    u, p = request.form["username"], request.form["password"]
    if len(u) < 2 or len(p) < 3:
        return render_template_string(REG_HTML, msg="", err="用户名至少2位，密码至少3位")
    if register_user(u, p):
        return render_template_string(REG_HTML, msg="注册成功，去登录", err="")
    return render_template_string(REG_HTML, msg="", err="用户名已存在")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return render_template_string(LOGIN_HTML, err="")

@app.route("/add_batch", methods=["POST"])
def add_batch():
    if "user" not in session: return jsonify({"msg": "未登录"})
    lines = [l.strip() for l in request.get_json()["text"].strip().split("\n") if l.strip()]
    col = get_user_collection(session["user"]); c = 0
    for line in lines:
        if "是" not in line: continue
        q, a = line.split("是", 1); q, a = q.strip(), a.strip()
        col.add(documents=[f"{q} | {a}"], embeddings=embed([q]), ids=[next_id(session["user"])], metadatas=[{"source": "manual"}]); c += 1
    return jsonify({"msg": f"成功存入 {c} \u6761"})

@app.route("/upload", methods=["POST"])
def upload():
    if "user" not in session: return jsonify({"msg": "未登录", "ok": False})
    f = request.files["file"]
    ext = f.filename.rsplit(".", 1)[-1].lower()
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, f.filename)
    f.save(path)
    try:
        if ext in ("txt",):
            loader = TextLoader(path, encoding="utf-8")
            docs = loader.load()
        elif ext == "pdf":
            loader = PyPDFLoader(path)
            docs = loader.load()
        elif ext == "docx":
            loader = UnstructuredWordDocumentLoader(path)
            docs = loader.load()
        elif ext in ("png", "jpg", "jpeg", "bmp"):
            if ocr is None:
                return jsonify({"msg": "图片识别未安装（缺少 PaddleOCR）", "ok": False})
            result = ocr.ocr(path, cls=True)
            text = "\n".join([line[1][0] for line in result[0]]) if result and result[0] else ""
            if not text.strip():
                return jsonify({"msg": "图片中未识别到文字", "ok": False})
            # 把 OCR 结果当作一个文档片段
            from langchain_core.documents import Document
            docs = [Document(page_content=text, metadata={"source": f.filename})]
        else:
            return jsonify({"msg": "不支持的文件格式", "ok": False})
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        col = get_user_collection(session["user"])
        texts = [c.page_content for c in chunks]
        vecs = embed(texts)
        ids = [next_id(session["user"]) for _ in texts]
        col.add(documents=texts, embeddings=vecs, ids=ids, metadatas=[{"source": f.filename} for _ in texts])
        return jsonify({"msg": f"成功：{f.filename} → 共{len(chunks)}条知识片段", "ok": True})
    except Exception as e:
        return jsonify({"msg": f"处理失败: {str(e)[:60]}", "ok": False})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def get_llm():
    global llm
    if llm is None and LLM_API_KEY:
        llm = ChatOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, model=LLM_MODEL, temperature=0.3)
    return llm

@app.route("/ask", methods=["POST"])
def ask():
    if "user" not in session: return jsonify({"answer": ""})
    q = request.get_json()["q"]

    t0 = time.time()
    col = get_user_collection(session["user"])
    r = col.query(query_embeddings=embed([q]), n_results=5)
    retrieval_t = round(time.time() - t0, 2)

    llm_client = get_llm()
    if not llm_client:
        fallback = ""
        if r["documents"][0]:
            fallback = r["documents"][0][0][:300] + "..."
        return jsonify({"answer": fallback})

    # 鍒ゆ柇妫€绱㈢粨鏋滄槸鍚︾浉鍏筹紙鍩轰簬 top-1 鍒嗘暟闃堝€硷級
    has_relevant = bool(r["documents"][0]) and (1 / (1 + r["distances"][0][0]) >= 0.45)

    t1 = time.time()
    try:
        if has_relevant:
            sources = [{"text": r["documents"][0][i], "score": round(1 / (1 + r["distances"][0][i]), 3)} for i in range(len(r["documents"][0]))]
            context_block = "\n\n".join([f"[{i+1}] {c}" for i, c in enumerate(r["documents"][0])])
            prompt = f"""你是一个专业的知识库问答助手。请基于以下参考资料回答问题。
要求：
- 如果问题与参考资料相关，请基于材料回答并用 [1][2] 上标标注来源
- 如果问题与参考资料无关，可以根据自己的知识正常回答
- 用中文回答，简洁准确
参考资料：
{context_block}

问题：{q}

回答："""
        else:
            sources = []
            prompt = f"""你是一个智能助手，请回答用户的问题。
要求：
- 用中文回答，简洁准确
- 不要编造信息
问题：{q}

回答："""
        resp = llm_client.invoke(prompt)
        thinking_t = round(time.time() - t1, 2)
        answer = resp.content
        meta = getattr(resp, "usage_metadata", {}) or {}
        return jsonify({
            "answer": answer, "sources": sources,
            "timing": {"retrieval": retrieval_t, "thinking": thinking_t},
            "tokens": {"input": meta.get("input_tokens", 0), "output": meta.get("output_tokens", 0)}
        })
    except Exception as e:
        err_text = r["documents"][0][0][:200] + "..." if r["documents"][0] else "请求失败"
        return jsonify({"answer": err_text, "sources": [], "error": str(e)[:60]})

@app.route("/data")
def get_data():
    if "user" not in session: return jsonify({"data": []})
    all_docs = get_user_collection(session["user"]).get()
    return jsonify({"data": [{"doc": doc, "id": all_docs["ids"][i]} for i, doc in enumerate(all_docs["documents"])]})

@app.route("/delete", methods=["POST"])
def delete():
    if "user" not in session: return jsonify({"ok": False})
    col = get_user_collection(session["user"])
    all_docs = col.get(); col.delete(ids=[all_docs["ids"][request.get_json()["idx"]]])
    _doc_counters[session["user"]] = col.count()
    return jsonify({"ok": True})

@app.route("/batch_delete", methods=["POST"])
def batch_delete():
    if "user" not in session: return jsonify({"ok": False})
    col = get_user_collection(session["user"])
    all_docs = col.get()
    ids = [all_docs["ids"][i] for i in request.get_json()["indices"]]
    col.delete(ids=ids)
    _doc_counters[session["user"]] = col.count()
    return jsonify({"ok": True})

@app.route("/clear_all", methods=["POST"])
def clear_all():
    if "user" not in session: return jsonify({"ok": False})
    client.delete_collection(f"user_{session['user']}")
    _doc_counters[session["user"]] = 0
    _ = get_user_collection(session["user"])  # 重新创建空集合    return jsonify({"ok": True})

@app.route("/count")
def count():
    if "user" not in session: return jsonify({"count": 0})
    return jsonify({"count": get_user_collection(session["user"]).count()})

@app.route("/conversations", methods=["GET"])
def get_convs():
    if "user" not in session: return jsonify([])
    return jsonify(load_convs(session["user"]))

@app.route("/conversations", methods=["POST"])
def save_conv():
    if "user" not in session: return jsonify({"ok": False})
    data = request.get_json()
    convs = load_convs(session["user"])
    existing = [c for c in convs if c.get("id") == data.get("id")]
    if existing:
        existing[0].update(data)
    else:
        data["id"] = f"c{int(time.time())}"
        data["created_at"] = datetime.now().isoformat()
        convs.insert(0, data)
    save_convs(session["user"], convs)
    return jsonify({"ok": True, "id": data["id"]})

@app.route("/conversations/<conv_id>", methods=["DELETE"])
def del_conv(conv_id):
    if "user" not in session: return jsonify({"ok": False})
    convs = load_convs(session["user"])
    save_convs(session["user"], [c for c in convs if c.get("id") != conv_id])
    return jsonify({"ok": True})

@app.route("/kb_docs")
def kb_docs():
    if "user" not in session: return jsonify({"docs": []})
    col = get_user_collection(session["user"])
    all_docs = col.get()
    items = []
    for i, (doc, id_) in enumerate(zip(all_docs["documents"], all_docs["ids"])):
        meta = all_docs["metadatas"][i] if all_docs.get("metadatas") else {}
        items.append({"id": id_, "text": doc, "idx": i, "source": (meta or {}).get("source", "unknown")})
    return jsonify({"docs": items})

@app.route("/health")
def health():
    return "ok", 200

if __name__ == "__main__":
    import socket, subprocess, time, sys
    port = int(os.environ.get("PORT", 5000))
    is_railway = os.environ.get("RAILWAY_SERVICE_ID") is not None
    TUNNEL_MODE = os.environ.get("TUNNEL_MODE", "bore" if os.name == "nt" and not is_railway else "")
    NGROK_TOKEN = os.environ.get("NGROK_TOKEN", "")
    public_url = None
    if not is_railway:
        def start_ngrok():
            try:
                from pyngrok import ngrok, conf
                conf.get_default().auth_token = NGROK_TOKEN
                return ngrok.connect(port, bind_tls=True).public_url
            except: return None
        def start_bore():
            try:
                bore_exe = os.path.expanduser(r"~\AppData\Local\ngrok\bore.exe")
                if not os.path.exists(bore_exe): return None
                subprocess.Popen([bore_exe, "local", str(port), "--to", "bore.pub"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(3); return "http://bore.pub"
            except: return None
        public_url = start_ngrok() if (NGROK_TOKEN or TUNNEL_MODE == "ngrok") else (start_bore() if TUNNEL_MODE == "bore" else None)
    local_ip = socket.gethostbyname(socket.gethostname())
    print("=" * 55)
    print(" 多用户 RAG 问答系统已启动")
    print(f" 本机访问:   http://127.0.0.1:{port}")
    print(f" 局域网访问: http://{local_ip}:{port}")
    if public_url: print(f" 外网访问:   {public_url}")
    print(f" LLM: {LLM_MODEL if LLM_API_KEY else '未配置'}")
    if os.name == "nt":
        print(f" Ctrl+B 切换侧栏 · Ctrl+K 聚焦输入 · Ctrl+L 新对话")
    print("=" * 55)
    app.run(debug=False, host="0.0.0.0", port=port)

