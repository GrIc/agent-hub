FROM python:3.12-slim

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY web/ web/
COPY agents/ agents/
COPY scripts/ scripts/
COPY config.yaml .
COPY watch.py .
COPY run.py .

RUN chmod +x scripts/*.sh

RUN mkdir -p context/docs context/architecture context/code-samples \
    workspace output/backups output/images reports web/logs

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/stats')" || exit 1

CMD ["python", "-m", "web.server", "--host", "0.0.0.0", "--port", "8080"]
