# Alarm system container — Raspberry Pi 5, GPIO via gpiozero/lgpio
# Build: docker build -t alarm .

FROM python:3.11-slim-bookworm

# gcc is needed to build the lgpio wheel; gpiod tools for debugging
RUN apt-get update && apt-get install -y \
    gcc \
    libgpiod-dev \
    python3-libgpiod \
    gpiod \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app/alarm

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir -r requirements.txt

COPY alarm.py .

CMD ["python3", "alarm.py"]
