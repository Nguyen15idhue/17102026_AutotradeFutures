FROM python:3.12-slim

# Khong root. TZ UTC theo AGENTS.md.
RUN useradd -m -u 10001 bot && mkdir -p /app /app/data && chown -R bot:bot /app
WORKDIR /app
USER bot

COPY --chown=bot:bot requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=bot:bot app/ ./app/

ENV TZ=UTC \
    PYTHONUNBUFFERED=1 \
    BINANCE_BASE_URL=http://binance-demo-server:8080 \
    BINANCE_WS_URL=ws://binance-demo-server:8080

# Heartbeat < 90s: main.py ghi epoch-ms vao /app/data/heartbeat moi 10s.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
  CMD python -c "import os,time,sys; p='/app/data/heartbeat'; sys.exit(0 if (os.path.exists(p) and time.time()-os.path.getmtime(p)<90) else 1)"

CMD ["python", "-m", "app.main"]
