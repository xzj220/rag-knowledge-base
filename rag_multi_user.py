"""
多用户 RAG 知识库问答系统 —— 本地模式入口

直接运行本文件即可在本机启动服务：
    python rag_multi_user.py

默认只监听本机（127.0.0.1），不对外网暴露。
如需让同一局域网内的手机/其它电脑访问，设置环境变量 HOST=0.0.0.0 后再启动。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from app.config import LLM_MODEL, LLM_API_KEY


if __name__ == "__main__":
    import socket

    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")  # 只监听本机；要局域网访问改成 0.0.0.0

    print("=" * 55)
    print(" 多用户 RAG 问答系统已启动（本地模式）")
    print(f" 本机访问:   http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
            print(f" 局域网访问: http://{local_ip}:{port}")
        except Exception:
            pass
    if LLM_API_KEY:
        print(f" LLM 模型:   {LLM_MODEL}")
    else:
        print(" LLM 模型:   未配置（AI 回答不可用，请在 .env 中填写 LLM_API_KEY）")
    print(" 按 Ctrl+C 退出")
    print("=" * 55)

    app.run(debug=False, host=host, port=port)
