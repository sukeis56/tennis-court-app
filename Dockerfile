FROM python:3.12-slim

# Playwright system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

RUN mkdir -p data

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
