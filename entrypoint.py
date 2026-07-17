import os, sys

port = os.environ.get("PORT", "5000")
print(f"[entrypoint] PORT={port!r}")
print(f"[entrypoint] All env PORT-related: {[(k,v) for k,v in sorted(os.environ.items()) if 'PORT' in k.upper()]}")

os.execvp("gunicorn", [
    "gunicorn",
    "rag_multi_user:app",
    "--bind", f"0.0.0.0:{port}",
    "--workers", "1",
    "--timeout", "300",
    "--worker-class", "sync",
])
