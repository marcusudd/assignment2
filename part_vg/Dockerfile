FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source — explicitly listed, never secrets
COPY config.toml .
COPY model_prices.json .
COPY .env.example .
COPY *.py .
COPY config/ config/

# Workspace sandbox — agent writes here only (VG.4 / D14)
RUN mkdir -p workspace

# Sessions dir for HG-2 provenance
RUN mkdir -p sessions

# Auto-approve bash in container (D14: sandbox IS the guard)
ENV AUTO_APPROVE=true

# Default: show help if no task given
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
