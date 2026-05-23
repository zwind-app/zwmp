FROM mcr.microsoft.com/playwright/python:v1.56.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ZWMP_CONFIG=/app/config/zwmp.config.json \
    ZWMP_DATA_DIR=/app/data \
    ZWMP_CACHE_DB=/app/data/cache/zwmp.sqlite3 \
    ZWMP_RULE_OUTPUT_DIR=/app/data/generated-rules

WORKDIR /app

COPY packages/rule-core /app/packages/rule-core
COPY apps/api /app/apps/api
COPY config /app/config
COPY scripts /app/scripts

RUN python -m pip install --upgrade pip \
    && pip install -e /app/packages/rule-core -e "/app/apps/api[browser]" \
    && python -m playwright install chromium

RUN mkdir -p /app/data/cache /app/data/generated-rules /app/.logs \
    && useradd --create-home --shell /usr/sbin/nologin zwmp \
    && chown -R zwmp:zwmp /app/data /app/.logs

USER zwmp

EXPOSE 8000

CMD ["uvicorn", "zwmp_api.main:app", "--app-dir", "/app/apps/api", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
