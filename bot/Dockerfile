# Telegram assistant bot — small Python image, long-polling (no exposed ports).
FROM python:3.12-slim

WORKDIR /app

# Install deps first so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bot source.
COPY bot/ ./bot/

# SQLite history lives here; mounted as a named volume in docker-compose.
ENV BOT_DB_PATH=/data/bot.db
VOLUME ["/data"]

CMD ["python", "-m", "bot.main"]
