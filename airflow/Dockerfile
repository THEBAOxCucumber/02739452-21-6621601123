# Build context is the project root (see docker-compose.yml) so the root requirements.txt is used.
FROM apache/airflow:2.10.5-python3.11
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
