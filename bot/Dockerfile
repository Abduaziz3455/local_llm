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

# Liveness: the bot touches /data/heartbeat every 30s. If polling hangs, the
# file goes stale and Docker restarts the container (restart: unless-stopped).
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,time,sys; f='/data/heartbeat'; sys.exit(0 if os.path.exists(f) and time.time()-os.path.getmtime(f) < 150 else 1)"

CMD ["python", "-m", "bot.main"]
