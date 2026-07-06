# VE.Direct → MQTT bridge for the Victron solar controller (Raspberry Pi 5)
# Build: docker build -t solar .
FROM python:3.11-slim-bookworm

# git is required for the rvglue git+https dependency in requirements.txt
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/solar

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir -r requirements.txt

COPY ve-direct.py .

ENV PYTHONUNBUFFERED=1

CMD ["python3", "ve-direct.py"]
