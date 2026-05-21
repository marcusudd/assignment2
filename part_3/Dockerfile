FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p workspace logs

# Unbuffered output so logs stream immediately
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
