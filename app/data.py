import json, sqlite3, hashlib, chromadb

from app.config import DATA_DIR, DB_PATH, CHROMA_PATH, CONV_DIR

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONV_DIR.mkdir(parents=True, exist_ok=True)

client = chromadb.PersistentClient(path=CHROMA_PATH)

def init_user_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
    conn.commit()
    conn.close()

init_user_db()

def register_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    pw = hashlib.sha256(password.encode()).hexdigest()
    try:
        conn.execute("INSERT INTO users VALUES (?, ?)", (username, pw))
        conn.commit()
        conn.close()
        return True
    except:
        conn.close()
        return False

def check_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    pw = hashlib.sha256(password.encode()).hexdigest()
    r = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, pw)).fetchone()
    conn.close()
    return r is not None

def load_convs(username):
    p = CONV_DIR / f"{username}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text("utf-8"))

def save_convs(username, convs):
    (CONV_DIR / f"{username}.json").write_text(
        json.dumps(convs, ensure_ascii=False, indent=2), "utf-8"
    )

def get_user_collection(username):
    name = f"user_{username}"
    try:
        return client.get_collection(name, embedding_function=None)
    except:
        return client.create_collection(name, embedding_function=None)

_doc_counters = {}
def next_id(username):
    col = get_user_collection(username)
    if username not in _doc_counters:
        _doc_counters[username] = col.count()
    _doc_counters[username] += 1
    return f"doc_{_doc_counters[username]}"
