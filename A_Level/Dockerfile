FROM python:3.11-slim

# System deps for pdf2image (Poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Faster rebuilds: install deps first
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt

# App code
COPY . /app

# Good defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# (Optional) run as non-root
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Start (fallback to 8080 if $PORT isn't set by the platform)
CMD ["sh", "-c", "uvicorn server_pipeline:app --host 0.0.0.0 --port ${PORT:-8080}"]