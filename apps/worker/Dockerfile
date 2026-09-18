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
COPY --chown=visualops:visualops app ./app

USER visualops
CMD ["celery", "-A", "app.runtime:celery_app", "worker", "--loglevel=INFO", "--queues=critical,default,media,analysis,exports,webhooks"]
