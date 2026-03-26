FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./backend/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        fastapi>=0.135.1 \
        google-genai>=1.66.0 \
        gunicorn>=23.0.0 \
        psycopg2>=2.9.11 \
        pydantic>=2.12.5 \
        python-dotenv>=1.2.2 \
        uvicorn[standard]>=0.41.0

EXPOSE 80

CMD ["gunicorn", "backend.main:app", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:80", "--workers", "1", "--timeout", "120", "--graceful-timeout", "30", "--keep-alive", "20", "--access-logfile", "-", "--error-logfile", "-"]
