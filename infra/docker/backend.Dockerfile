FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./backend/pyproject.toml

RUN pip install --no-cache-dir --upgrade pip \
    && python -c "import tomllib, pathlib; pyproject = tomllib.loads(pathlib.Path('/app/backend/pyproject.toml').read_text(encoding='utf-8')); deps = pyproject['project']['dependencies']; pathlib.Path('/tmp/requirements.txt').write_text('\\n'.join(deps) + '\\n', encoding='utf-8')" \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/ ./backend/

EXPOSE 80

CMD ["gunicorn", "backend.main:app", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:80", "--workers", "1", "--timeout", "120", "--graceful-timeout", "30", "--keep-alive", "20", "--access-logfile", "-", "--error-logfile", "-"]
