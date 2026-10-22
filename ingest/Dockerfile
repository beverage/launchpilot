FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY ingest/requirements.txt ingest/requirements.txt
RUN pip install --no-cache-dir -r ingest/requirements.txt

COPY ingest ingest
COPY streams streams

EXPOSE 8080
CMD ["python", "-m", "ingest.run"]
