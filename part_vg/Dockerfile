# ── Stage 1: build React GUI ─────────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime + web server ───────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend source (never copy .env — secrets via env_file at runtime)
COPY config.toml model_prices.json .env.example ./
COPY *.py ./
COPY config/ config/
COPY scripts/ scripts/
COPY fixtures/ fixtures/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN mkdir -p workspace logs sessions \
    && chmod +x scripts/reset_seed.sh

ENV AUTO_APPROVE=true
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
