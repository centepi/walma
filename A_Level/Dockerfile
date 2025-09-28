FROM python:3.11-slim

# System deps for pdf2image (Poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Faster rebuilds: install deps first
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt

# Copy only backend code needed at runtime
COPY server_pipeline.py /app/server_pipeline.py
COPY pipeline_scripts /app/pipeline_scripts
COPY config /app/config

# Good defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# (Optional) run as non-root
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Start (use $PORT if provided by the platform)
CMD ["sh", "-c", "uvicorn server_pipeline:app --host 0.0.0.0 --port ${PORT:-8080}"]