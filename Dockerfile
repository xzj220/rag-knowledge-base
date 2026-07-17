FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 -r requirements.txt

COPY . .

RUN mkdir -p /data/chroma /data/conversations /root/.cache/huggingface

ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/data
ENV HF_ENDPOINT=https://hf-mirror.com

EXPOSE $PORT

CMD python rag_multi_user.py
