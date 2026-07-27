FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY app /app/app
RUN pip install --upgrade pip && pip install ".[dev]"

COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations
COPY fixtures /app/fixtures
COPY tests /app/tests

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4200"]

