# RainReady API / worker image (also serves the exported UI when STATIC_DIR is set).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/api
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY rainready ./rainready

RUN useradd -r -u 10001 rainready && mkdir -p /app/api/data && chown -R rainready /app/api
USER rainready

EXPOSE 8100
CMD ["uvicorn", "rainready.main:app", "--host", "0.0.0.0", "--port", "8100"]
