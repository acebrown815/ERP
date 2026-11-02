FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

RUN useradd --create-home --uid 10001 erp && mkdir -p /data/attachments /data/backups && chown erp /data/attachments /data/backups
USER erp
ENV ERP_ATTACHMENTS_DIR=/data/attachments ERP_BACKUPS_DIR=/data/backups

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
