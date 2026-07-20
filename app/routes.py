import time, re, os, tempfile, shutil, traceback
from datetime import datetime

from flask import request, jsonify, render_template_string, session
from langchain_community.document_loaders import TextLoader, PyPDFLoader, UnstructuredWordDocumentLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import app
from app.templates import LOGIN_HTML, REG_HTML, MAIN_HTML
from app.data import (client, _doc_counters, get_user_collection, load_convs,
                      save_convs, next_id, register_user, check_user)
from app.services import embed, get_llm, ocr


@app.route("/")
def index():
    if "user" in session:
        return render_template_string(MAIN_HTML, user=session["user"])
    return render_template_string(LOGIN_HTML, err="")


@app.route("/login", methods=["POST"])
def login():
    u, p = request.form["username"], request.form["password"]
    if check_user(u, p):
        session["user"] = u
        get_user_collection(u)
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
    if "user" not in session:
        return jsonify({"msg": "未登录"})
    try:
        data = request.get_json()
        if not data or "text" not in data:
            return jsonify({"msg": "请求数据格式错误"})
        lines = [l.strip() for l in data["text"].strip().split("\n") if l.strip()]
        col = get_user_collection(session["user"])
        c = 0
        for line in lines:
            if "是" not in line:
                continue
            q, a = line.split("是", 1)
            q, a = q.strip(), a.strip()
            col.add(documents=[f"{q} | {a}"], embeddings=embed([q]),
                    ids=[next_id(session["user"])], metadatas=[{"source": "manual"}])
            c += 1
        return jsonify({"msg": f"成功存入 {c} 条"})
    except Exception as e:
        print(f"add_batch error: {traceback.format_exc()}")
        return jsonify({"msg": f"处理失败: {str(e)[:120]}", "ok": False})


@app.route("/upload", methods=["POST"])
def upload():
    if "user" not in session:
        return jsonify({"msg": "未登录", "ok": False})
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
        col.add(documents=texts, embeddings=vecs, ids=ids,
                metadatas=[{"source": f.filename} for _ in texts])
        return jsonify({"msg": f"成功：{f.filename} → 共{len(chunks)}条知识片段", "ok": True})
    except Exception as e:
        return jsonify({"msg": f"处理失败: {str(e)[:60]}", "ok": False})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.route("/ask", methods=["POST"])
def ask():
    if "user" not in session:
        return jsonify({"answer": ""})
    data = request.get_json()
    q = data["q"]
    conv_id = data.get("conv_id")

    history = ""
    if conv_id:
        convs = load_convs(session["user"])
        for c in convs:
            if c.get("id") == conv_id:
                msgs = c.get("messages", [])[-6:]
                history = "\n".join(
                    [f"{'用户' if m['role']=='user' else '助手'}: {re.sub(r'<[^>]+>', '', m.get('html', ''))[:300]}" for m in msgs]
                )
                break

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

    has_relevant = bool(r["documents"][0]) and (1 / (1 + r["distances"][0][0]) >= 0.3)

    t1 = time.time()
    try:
        history_block = f"\n历史对话：\n{history}\n" if history else ""
        if has_relevant:
            sources = [{"text": r["documents"][0][i], "score": round(1 / (1 + r["distances"][0][i]), 3)}
                       for i in range(len(r["documents"][0]))]
            context_block = "\n\n".join([f"[{i+1}] {c}" for i, c in enumerate(r["documents"][0])])
            prompt = f"""你是一个专业的知识库问答助手。请基于以下参考资料回答问题。
要求：
- 如果问题与参考资料相关，请基于材料回答并用 [1][2] 上标标注来源
- 如果问题与参考资料无关，可以根据自己的知识正常回答
- 用中文回答，简洁准确
参考资料：
{context_block}
{history_block}
新问题：{q}

回答："""
        else:
            sources = []
            prompt = f"""你是一个智能助手，请回答用户的问题。
要求：
- 用中文回答，简洁准确
- 不要编造信息
{history_block}
新问题：{q}

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
    if "user" not in session:
        return jsonify({"data": []})
    all_docs = get_user_collection(session["user"]).get()
    return jsonify({"data": [{"doc": doc, "id": all_docs["ids"][i]}
                             for i, doc in enumerate(all_docs["documents"])]})


@app.route("/delete", methods=["POST"])
def delete():
    if "user" not in session:
        return jsonify({"ok": False})
    col = get_user_collection(session["user"])
    all_docs = col.get()
    col.delete(ids=[all_docs["ids"][request.get_json()["idx"]]])
    _doc_counters[session["user"]] = col.count()
    return jsonify({"ok": True})


@app.route("/batch_delete", methods=["POST"])
def batch_delete():
    if "user" not in session:
        return jsonify({"ok": False})
    col = get_user_collection(session["user"])
    all_docs = col.get()
    ids = [all_docs["ids"][i] for i in request.get_json()["indices"]]
    col.delete(ids=ids)
    _doc_counters[session["user"]] = col.count()
    return jsonify({"ok": True})


@app.route("/clear_all", methods=["POST"])
def clear_all():
    if "user" not in session:
        return jsonify({"ok": False})
    client.delete_collection(f"user_{session['user']}")
    _doc_counters[session["user"]] = 0
    _ = get_user_collection(session["user"])
    return jsonify({"ok": True})


@app.route("/count")
def count():
    if "user" not in session:
        return jsonify({"count": 0})
    return jsonify({"count": get_user_collection(session["user"]).count()})


@app.route("/conversations", methods=["GET"])
def get_convs():
    if "user" not in session:
        return jsonify([])
    return jsonify(load_convs(session["user"]))


@app.route("/conversations", methods=["POST"])
def save_conv():
    if "user" not in session:
        return jsonify({"ok": False})
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
    if "user" not in session:
        return jsonify({"ok": False})
    convs = load_convs(session["user"])
    save_convs(session["user"], [c for c in convs if c.get("id") != conv_id])
    return jsonify({"ok": True})


@app.route("/kb_docs")
def kb_docs():
    if "user" not in session:
        return jsonify({"docs": []})
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
