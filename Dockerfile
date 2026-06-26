FROM python:3.11-slim

WORKDIR /app

# Build deps for psycopg and sentence-transformers' tokenizer deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only torch FIRST, from PyTorch's dedicated index. This skips
# ~1.5-2GB of NVIDIA CUDA libraries (cublas, cudnn, cufft, curand, cusolver,
# nccl, etc.) that the default PyPI torch wheel pulls in for GPU support we
# don't use -- this app only does CPU embedding inference on a small model.
RUN pip install --no-cache-dir torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model at build time so the first request
# doesn't pay a multi-hundred-MB download cost. Placed BEFORE the COPY
# steps below (and depends only on requirements.txt, not on app code) so
# that editing app/, scripts/, or data/ never invalidates this layer and
# never re-triggers the model download on a rebuild.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('intfloat/multilingual-e5-base')"

COPY app/ ./app/
COPY scripts/ ./scripts/
COPY data/ ./data/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
