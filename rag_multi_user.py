import os, sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from app.config import LLM_MODEL, LLM_API_KEY

if __name__ == "__main__":
    import socket, subprocess, time
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
