import os
from rag_multi_user import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[entrypoint] Starting on port {port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
