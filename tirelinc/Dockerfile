# TireLinc TPMS monitor — BLE via bleak (uses D-Bus/bluetoothd)
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y \
    bluez \
    bluez-tools \
    bluetooth \
    rfkill \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/tirelinc

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir -r requirements.txt

COPY tirelinc_monitor.py .

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

CMD ["python3", "tirelinc_monitor.py"]
