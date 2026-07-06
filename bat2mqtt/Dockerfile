# Battery monitor — BLE via gatttool (deprecated upstream but works on bookworm;
# see plan item 22 for the eventual bleak migration)
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y \
    bluez \
    bluez-tools \
    bluetooth \
    rfkill \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/bat2mqtt

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir -r requirements.txt

COPY bat2mqtt.py .

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

CMD ["python3", "bat2mqtt.py"]
