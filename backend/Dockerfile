FROM python:3.12-slim-bookworm

WORKDIR /app

RUN useradd --create-home --shell /bin/bash appuser

RUN mkdir -p /app/data/parlgov && chown appuser:appuser /app/data /app/data/parlgov

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data/thresholds.json ./data/thresholds.json

USER appuser

ENV PYTHONUNBUFFERED=1
ENV PARLGOV_DATA_DIR=/app/data/parlgov

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
