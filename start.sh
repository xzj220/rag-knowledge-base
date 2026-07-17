#!/bin/bash
set -e

echo ">>> PORT env = [${PORT}]"

echo ">>> Downloading embedding model (background)..."
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')" 2>&1 &

echo ">>> Starting gunicorn..."
exec gunicorn rag_multi_user:app --bind "0.0.0.0:${PORT:-5000}" --workers 1 --timeout 300 --worker-class sync
