# AgentMan backend image.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agentman ./agentman
COPY alembic.ini .
COPY migrations ./migrations

# Writable data dir for the SQLite db (mount a volume here).
RUN useradd --create-home --uid 10001 appuser && mkdir /data && chown appuser /data
USER appuser

EXPOSE 8100
CMD ["uvicorn", "agentman.main:app", "--host", "0.0.0.0", "--port", "8100"]
