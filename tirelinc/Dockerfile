FROM python:3.11-slim-bookworm

# Install system dependencies for Bluetooth (bleak uses D-Bus/bluetoothd)
RUN apt-get update && apt-get install -y \
    bluez \
    bluez-tools \
    bluetooth \
    rfkill \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tirelinc
WORKDIR /app/tirelinc

COPY tirelinc_monitor.py .
COPY requirements.txt .

RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install -r requirements.txt

RUN chmod +x tirelinc_monitor.py

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

CMD ["python3", "tirelinc_monitor.py"]