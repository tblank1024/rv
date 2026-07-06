# MQTT/RV-C data watcher/logger
# tk stays: watcher.py imports tkinter unconditionally (live-view mode)
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    gcc \
    tk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/watcher
RUN mkdir -p watcherlogs

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir -r requirements.txt

COPY watcher.py .

ENV PYTHONUNBUFFERED=1

CMD ["python3", "watcher.py"]
