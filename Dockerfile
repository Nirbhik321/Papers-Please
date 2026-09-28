# Papers Please API — sized for Render's free tier (512 MB RAM, 0.1 CPU).
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/app/.hf

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image so a cold start never downloads it
RUN python -c "from huggingface_hub import hf_hub_download as d; \
r='sentence-transformers/paraphrase-MiniLM-L6-v2'; d(r,'onnx/model.onnx'); d(r,'tokenizer.json')"
ENV HF_HUB_OFFLINE=1

COPY subjects.yaml .
COPY modules modules
COPY server server

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
