FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY data/store_info.md data/catalog_sample.csv ./data/

# data/ holds the SQLite database and store_info.md — mount it as a volume to keep them across deploys.
VOLUME ["/app/data"]
CMD ["python", "-m", "bot"]
