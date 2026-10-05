FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# WITH_READER=true (default): the API reads PDFs/photos itself (needs Tesseract OCR, runs locally).
# WITH_READER=false: slim API image; run the separate invoice-reader service (Dockerfile.reader) instead.
ARG WITH_READER=true

WORKDIR /app
RUN if [ "$WITH_READER" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ron tesseract-ocr-eng \
      && rm -rf /var/lib/apt/lists/*; \
    fi

COPY requirements-api.txt requirements-reader.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt \
    && if [ "$WITH_READER" = "true" ]; then pip install --no-cache-dir -r requirements-reader.txt; fi \
    && useradd --system --uid 10001 --no-create-home app

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
