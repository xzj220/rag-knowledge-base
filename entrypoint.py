import os, sys

if __name__ == "__main__":
    port = os.environ.get("PORT", "5000")
    os.execvp("gunicorn", [
        "gunicorn",
        "rag_multi_user:app",
        "--bind", f"0.0.0.0:{port}",
        "--workers", "1",
        "--timeout", "300",
        "--worker-class", "sync",
    ])
