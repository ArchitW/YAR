FROM python:3.12-slim
WORKDIR /app
ENV HF_HOME=/root/.cache/huggingface
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ARG PREFETCH_MODELS=false
RUN if [ "$PREFETCH_MODELS" = "true" ]; then \
      python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer('BAAI/bge-m3', device='cpu'); CrossEncoder('BAAI/bge-reranker-base', device='cpu')"; \
    fi
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
