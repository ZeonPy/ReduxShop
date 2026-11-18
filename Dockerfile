FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bothost bind-mounts /app at runtime, so create the data dir on start.
CMD ["sh", "-c", "mkdir -p /app/data && exec python -u bot.py"]
