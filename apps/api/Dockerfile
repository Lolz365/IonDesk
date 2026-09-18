FROM python:3.13.13-slim AS runtime

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 visualops \
    && useradd --system --uid 10001 --gid visualops --home-dir /app visualops

WORKDIR /app
COPY --chown=visualops:visualops pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.8.15 \
    && uv sync --frozen --no-dev --no-editable \
    && chown -R visualops:visualops /app
COPY --chown=visualops:visualops alembic.ini ./alembic.ini
COPY --chown=visualops:visualops alembic ./alembic
COPY --chown=visualops:visualops app ./app

USER visualops
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
