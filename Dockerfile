FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md /app/
RUN mkdir -p /app/app && touch /app/app/__init__.py
RUN pip install --upgrade pip && pip install ".[dev]"
RUN pip uninstall -y notaritmo && rm -rf /app/app

COPY app /app/app
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations
COPY fixtures /app/fixtures
COPY tests /app/tests
COPY scripts /app/scripts

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4200"]
