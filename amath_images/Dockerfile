# amath_images/Dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# System deps: Cairo/Pango for CairoSVG, plus Node.js 20
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg ca-certificates build-essential \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi8 \
    fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# Install Node 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get update && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Node deps
COPY package.json /app/package.json
RUN npm install --omit=dev

# App source
COPY . /app

# Start (Railway provides $PORT)
CMD ["sh","-c","python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]