FROM python:3.12-slim

LABEL maintainer="srockci"
LABEL description="Apple Reminders <-> Zectrix bidirectional sync"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY db/ ./db/

ENV PYTHONUNBUFFERED=1

# Run as non-root
RUN useradd -m -u 1000 syncer
USER syncer

CMD ["python", "-m", "app.cli", "--config", "/data/config.yaml"]