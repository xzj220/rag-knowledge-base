#!/bin/bash
set -e

echo ">>> Downloading embedding model..."
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

echo ">>> Starting gunicorn..."
exec gunicorn rag_multi_user:app --bind 0.0.0.0:$PORT --workers 1 --timeout 300 --worker-class sync
