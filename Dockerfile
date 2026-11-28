FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app
COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./
RUN pip install --upgrade pip && pip install .
USER app
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 CMD ["python", "-m", "app.healthcheck"]
CMD ["python", "-m", "app"]
