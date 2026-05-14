FROM python:3.11-slim

WORKDIR /app

# Install basic tools the agent might use
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    tree \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
