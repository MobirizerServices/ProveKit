# ProveKit backend image.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=sqlite:////data/provekit.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY provekit ./provekit
COPY alembic.ini .

# Writable data dir for the SQLite db (mount a volume here). Owned by the app
# uid so the default DATABASE_URL (sqlite:////data/provekit.db) works standalone.
RUN useradd --create-home --uid 10001 appuser && mkdir /data && chown 10001:10001 /data
USER appuser

# Port 8000 to match the provekit.online gateway contract. --proxy-headers +
# --forwarded-allow-ips lets the app read X-Forwarded-For/Proto from nginx, so rate limits
# and the real client IP work behind the reverse proxy.
EXPOSE 8000
CMD ["uvicorn", "provekit.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
