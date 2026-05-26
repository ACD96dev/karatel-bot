FROM python:3.12-slim

WORKDIR /app

# gcc needed to compile lxml if no wheel is available
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/

# Non-root user for security
RUN useradd -r -u 1001 -s /sbin/nologin karabot && \
    mkdir -p /data && chown karabot:karabot /data

USER karabot

VOLUME ["/data"]

CMD ["python", "-m", "bot.main"]
