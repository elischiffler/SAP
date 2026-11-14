FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock \
    && groupadd --gid 10001 sap \
    && useradd --uid 10001 --gid sap --no-create-home --shell /usr/sbin/nologin sap \
    && install -d -o sap -g sap -m 0700 /data

COPY contracts/ ./contracts/
COPY server/ ./server/
COPY intelligence/ ./intelligence/
COPY prompts/ ./prompts/
COPY web/ ./web/

USER sap
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=3 \
  CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/healthz', timeout=3).close()"]

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "32", "--backlog", "64", "--timeout-keep-alive", "5", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
